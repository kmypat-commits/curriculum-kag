"""Retrieval of the scoped EPVO catalogue used by variant planning.

The planner may use semantic evidence for ranking, but catalogue scope is a
separate concern: the selected direction/group and education level must be
resolved before candidates enter the variant frontier.  Keeping this query in
one small module makes that boundary auditable and prevents ranking code from
silently broadening the domain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.course import Course
from app.models.epvo import EpvoDisciplineNormalized
from app.models.project import ProjectVersion
from app.planner.domain_evidence import domain_credit_shares
from app.services.epvo_repository import epvo_row_relevance_score


@dataclass(slots=True)
class EpvoScopeIndex:
    """Resolved EPVO scope and tie-break evidence for one project version."""

    scope_by_title: dict[str, int] = field(default_factory=dict)
    priority_by_title: dict[str, int] = field(default_factory=dict)
    scope_by_course: dict[int, int] = field(default_factory=dict)
    priority_by_course: dict[int, int] = field(default_factory=dict)
    domain_evidence_by_course: dict[int, list[int]] = field(default_factory=dict)
    semester_values_by_course: dict[int, list[int]] = field(default_factory=dict)
    level_scope_allowed_ids: set[int] = field(default_factory=set)
    domain_index_by_course: dict[int, int] = field(default_factory=dict)
    domain_shares_by_course: dict[int, tuple[float, float]] = field(default_factory=dict)


def build_epvo_scope_index(
    db: Session,
    *,
    version: ProjectVersion,
    constraints: Mapping[str, object],
    aggregates: Mapping[int, Mapping[str, object]],
    courses: Mapping[int, Course],
    title_key,
) -> EpvoScopeIndex:
    """Return only catalogue rows admissible for the selected EPVO scope.

    ``aggregates`` is intentionally supplied by the caller.  This keeps the
    retrieval stage tied to project-specific course--LO evidence and avoids a
    second broad scan of the multi-million-link EPVO table.
    """

    result = EpvoScopeIndex()
    group_codes = [
        str(value or "").strip()
        for value in (constraints.get("group_code"), constraints.get("secondary_group_code"))
        if str(value or "").strip()
    ]
    direction_codes = [
        str(value or "").strip()
        for value in (constraints.get("direction_code"), constraints.get("secondary_direction_code"))
        if str(value or "").strip()
    ]
    if not (group_codes or direction_codes):
        return result

    primary_group = str(constraints.get("group_code") or "").strip()
    secondary_group = str(constraints.get("secondary_group_code") or "").strip()
    primary_direction = str(constraints.get("direction_code") or "").strip()
    secondary_direction = str(constraints.get("secondary_direction_code") or "").strip()
    scope_conditions = [
        cast(EpvoDisciplineNormalized.group_codes, String).like(f'%"{code}"%')
        for code in group_codes
    ] + [
        cast(EpvoDisciplineNormalized.direction_codes, String).like(f'%"{code}"%')
        for code in direction_codes
    ]
    matched_rows = db.query(EpvoDisciplineNormalized).filter(
        EpvoDisciplineNormalized.approved_course_id.isnot(None),
        EpvoDisciplineNormalized.approved_course_id.in_(list(aggregates) or [-1]),
        or_(*scope_conditions),
    ).all()
    total_semesters = int(constraints.get("total_semesters") or 8)
    for row in matched_rows:
        row_groups = row.group_codes or []
        row_directions = row.direction_codes or []
        rank_value = (
            3 if any(code in row_groups for code in group_codes)
            else 2 if any(code in row_directions for code in direction_codes)
            else 0
        )
        if rank_value <= 0:
            continue
        source_count = len(row.source_programs or [])
        relevance_value = epvo_row_relevance_score(row, version)
        programme_evidence = aggregates.get(int(row.approved_course_id), {})
        strong_program_evidence = (
            float(programme_evidence.get("max") or 0.0) >= float(settings.COVERAGE_THRESHOLD)
            or float(programme_evidence.get("expert") or 0.0) >= 0.5
        )
        # Exact group membership is a strong catalogue signal.  The lighter
        # title relevance fallback is applied only to direction-level matches.
        if relevance_value < 0.52 and rank_value < 3 and not strong_program_evidence:
            continue
        course_id = int(row.approved_course_id)
        result.level_scope_allowed_ids.add(course_id)
        typical_semester = int(row.typical_semester or 0)
        if 1 <= typical_semester <= total_semesters:
            result.semester_values_by_course.setdefault(course_id, []).append(typical_semester)
        priority_value = int(relevance_value * 1000) + rank_value * 100 + min(source_count, 50) * 5
        primary_scope = (
            3 if primary_group and primary_group in row_groups
            else 2 if primary_direction and primary_direction in row_directions
            else 0
        )
        secondary_scope = (
            3 if secondary_group and secondary_group in row_groups
            else 2 if secondary_direction and secondary_direction in row_directions
            else 0
        )
        mapped_course = courses.get(course_id)
        if mapped_course:
            result.scope_by_course[mapped_course.id] = max(
                result.scope_by_course.get(mapped_course.id, 0), rank_value
            )
            result.priority_by_course[mapped_course.id] = max(
                result.priority_by_course.get(mapped_course.id, 0), priority_value
            )
            evidence = result.domain_evidence_by_course.setdefault(mapped_course.id, [0, 0])
            evidence[0] = max(evidence[0], primary_scope)
            evidence[1] = max(evidence[1], secondary_scope)
        for title in (row.title_ru, row.title_kk, row.title_en):
            if title:
                key = title_key(title)
                result.scope_by_title[key] = max(result.scope_by_title.get(key, 0), rank_value)
                result.priority_by_title[key] = max(
                    result.priority_by_title.get(key, 0), priority_value
                )

    for course_id, (primary_score, secondary_score) in result.domain_evidence_by_course.items():
        if primary_score or secondary_score:
            result.domain_shares_by_course[course_id] = domain_credit_shares(
                primary_score, secondary_score
            )
            result.domain_index_by_course[course_id] = (
                1 if secondary_score > primary_score else 0
            )
    return result
