"""Evidence reconstruction for late scheduler replacements."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from app.models.embedding import MatchScore
from app.models.course import Course
from app.planner.course_policy import education_level_course_allowed
from app.planner.domain_evidence import domain_label_matches


def recover_professional_evidence(
    item: dict[str, Any],
    *,
    project_version_id: int,
    professional_los: Iterable[Any],
    db: Session,
) -> dict[str, Any]:
    """Attach canonical LO evidence to a late-added real course.

    Repairs often carry a course id but not the denormalized admission fields.
    Rebuilding those fields from MatchScore keeps the admission boundary
    auditable and avoids deleting valid courses merely because they entered
    through a repair path.
    """
    if item.get("admission_los") or item.get("course_id") is None:
        return item
    lo_codes = {
        lo.id: str(lo.lo_code or "")
        for lo in professional_los
        if str(lo.lo_code or "")
    }
    if not lo_codes:
        return item
    recovered_los: set[str] = set()
    recovered_score = 0.0
    for match in db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version_id,
        MatchScore.course_id == int(item["course_id"]),
        MatchScore.lo_id.in_(list(lo_codes)),
    ).all():
        expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        effective = max(float(match.score or 0.0), expert)
        if effective >= 0.4:
            recovered_los.add(lo_codes[match.lo_id])
            recovered_score = max(recovered_score, effective)
    if recovered_los:
        item["admission_los"] = sorted(recovered_los)
        item["admission_score"] = round(recovered_score, 4)
    return item


def sanitize_admitted_course_items(
    items: list[dict[str, Any]],
    *,
    project_version_id: int,
    professional_los: Iterable[Any],
    project_domains: Iterable[str],
    constraints: dict[str, Any],
    is_project_domain,
    curriculum_role,
    match_max_by_course: dict[int, float],
    db: Session,
) -> list[dict[str, Any]]:
    """Apply the final real-course admission boundary after scheduler repairs."""
    cleaned: list[dict[str, Any]] = []
    domains = [str(value or "").casefold().strip() for value in project_domains]
    for raw_item in items:
        item = dict(raw_item)
        if item.get("regulatory_required") or item.get("course_id") is None:
            cleaned.append(item)
            continue
        course = db.get(Course, item["course_id"])
        if course is None:
            continue
        item = recover_professional_evidence(
            item,
            project_version_id=project_version_id,
            professional_los=professional_los,
            db=db,
        )
        code = str(course.course_id or "")
        if code.startswith("GOSO-KZ-") and str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() == "KZ":
            item["regulatory_required"] = True
            cleaned.append(item)
            continue
        if not item.get("admission_los") or not education_level_course_allowed(course, constraints.get("education_level")):
            continue
        item_domain = str(item.get("domain") or "").casefold().strip()
        item_domain_matches = bool(item_domain) and (
            any(domain and (domain in item_domain or item_domain in domain) for domain in domains)
            or domain_label_matches(item_domain, domains)
        )
        strong_epvo_scope = code.startswith("EPVO-") and match_max_by_course.get(course.id, 0.0) >= 0.8
        if not is_project_domain(course) and not item_domain_matches and not strong_epvo_scope:
            continue
        if curriculum_role(course, domains) == "general" and match_max_by_course.get(course.id, 0.0) < 0.55:
            continue
        cleaned.append(item)
    return cleaned
