"""Cheap preflight checks for programme-level EPVO/LO evidence.

The planner may only use bridge modules as a bounded fallback.  This module
checks whether the selected EPVO scopes have enough *credible* professional
course evidence before the expensive variant scheduler is started.  It does
not invent links and it never lowers the final admission threshold.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.embedding import MatchScore
from app.models.epvo import EpvoDisciplineNormalized
from app.models.project import ProjectVersion
from app.services.epvo_repository import epvo_row_matches_education_level


def evaluate_scoped_evidence(
    *,
    courses: Iterable[Course],
    scoped_course_ids: dict[int, tuple[bool, bool]],
    credible_course_ids: set[int],
    constraints: dict,
) -> dict:
    """Evaluate evidence credit by domain without changing planner state.

    Courses that belong to both selected scopes are split equally, matching the
    domain-credit policy used by the verifier.  Standard programmes are
    intentionally skipped: this guard is for dual-domain retrieval starvation.
    """
    programme_type = str(constraints.get("program_type") or "standard").lower()
    interdisciplinary = programme_type in {"interdisciplinary", "joint"}
    has_secondary_scope = bool(
        str(constraints.get("secondary_group_code") or "").strip()
        or str(constraints.get("secondary_direction_code") or "").strip()
    )
    if not interdisciplinary or not has_secondary_scope:
        return {"blocking": False, "skipped": True, "reason": "not_interdisciplinary"}

    available = [0.0, 0.0]
    contributing = [set(), set()]
    for course in courses:
        course_id = int(course.id)
        if course_id not in credible_course_ids:
            continue
        membership = scoped_course_ids.get(course_id, (False, False))
        memberships = [index for index, matched in enumerate(membership) if matched]
        if not memberships:
            continue
        credits = float(course.credits or 0.0)
        share = credits / len(memberships)
        for index in memberships:
            available[index] += share
            contributing[index].add(course_id)

    target = float(constraints.get("total_credits") or 0.0)
    required = [
        target * max(0.0, float(constraints.get("min_domain1_percent") or 0.0)) / 100.0,
        target * max(0.0, float(constraints.get("min_domain2_percent") or 0.0)) / 100.0,
    ]
    tolerance = max(0.0, float(constraints.get("credit_tolerance") or 0.0))
    deficits = [max(0.0, required[index] - tolerance - available[index]) for index in range(2)]
    return {
        "blocking": any(deficit > 0.0 for deficit in deficits),
        "skipped": False,
        "available_credits": [round(value, 2) for value in available],
        "required_credits": [round(value, 2) for value in required],
        "deficits": [round(value, 2) for value in deficits],
        "credible_courses": [len(contributing[0]), len(contributing[1])],
        "message": (
            "Недостаточно подтверждённых EPVO/LO-доказательств для выбранных направлений. "
            "Пересчитайте связи дисциплина–РО или подтвердите экспертные связи перед генерацией."
        ) if any(deficit > 0.0 for deficit in deficits) else "EPVO/LO evidence is sufficient for both selected scopes.",
    }


def assess_professional_evidence(version: ProjectVersion, db: Session) -> dict:
    """Build the preflight input from PostgreSQL rows for one project version."""
    constraints = dict(version.project.constraints_json or {})
    outcomes = {
        int(lo.id): str(lo.lo_code or "")
        for lo in version.learning_outcomes
        if not str(lo.lo_code or "").upper().startswith("LO-GOSO-")
    }
    match_rows = db.query(MatchScore).filter(
        MatchScore.project_version_id == version.id,
        MatchScore.lo_id.in_(set(outcomes) or {-1}),
    ).all()
    matched_course_ids = {
        int(row.course_id) for row in match_rows if row.course_id is not None
    }
    courses = db.query(Course).filter(
        Course.id.in_(matched_course_ids or {-1}),
        Course.course_id.like("EPVO-%"),
    ).all()
    course_ids = {int(course.id) for course in courses}
    credible_course_ids: set[int] = set()
    for match in match_rows:
        if match.course_id not in course_ids:
            continue
        expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        if max(float(match.score or 0.0), expert) >= 0.4:
            credible_course_ids.add(int(match.course_id))

    scope_pairs = [
        (str(constraints.get("group_code") or ""), str(constraints.get("direction_code") or "")),
        (str(constraints.get("secondary_group_code") or ""), str(constraints.get("secondary_direction_code") or "")),
    ]
    scoped_course_ids: dict[int, tuple[bool, bool]] = defaultdict(lambda: [False, False])
    normalized = db.query(EpvoDisciplineNormalized).filter(
        EpvoDisciplineNormalized.approved_course_id.in_(course_ids or {-1})
    ).all()
    for row in normalized:
        if not epvo_row_matches_education_level(row, constraints.get("education_level")):
            continue
        groups = {str(value or "") for value in (row.group_codes or [])}
        directions = {str(value or "") for value in (row.direction_codes or [])}
        membership = [
            bool(group and group in groups or direction and direction in directions)
            for group, direction in scope_pairs
        ]
        course_id = row.approved_course_id
        if course_id and any(membership):
            scoped_course_ids[int(course_id)] = [
                scoped_course_ids[int(course_id)][index] or membership[index]
                for index in range(2)
            ]
    result = evaluate_scoped_evidence(
        courses=courses,
        scoped_course_ids=dict(scoped_course_ids),
        credible_course_ids=credible_course_ids,
        constraints=constraints,
    )
    result.update({"project_version_id": int(version.id), "credible_course_count": len(credible_course_ids)})
    return result
