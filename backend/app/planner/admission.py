"""Independent admission evidence checks for persisted curriculum courses."""

from __future__ import annotations

from typing import Dict

from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.embedding import MatchScore
from app.models.epvo import EpvoDisciplineNormalized
from app.models.project import ProjectVersion
from app.planner.course_policy import (
    course_curriculum_role,
    education_level_course_allowed,
    project_domain_terms,
)
from app.planner.scheduler_domain_rules import course_domain_matches
from app.planner.semester_rules import minimum_appropriate_semester as item_minimum_appropriate_semester
from app.services.epvo_repository import epvo_row_matches_education_level


def minimum_appropriate_semester(item: Dict, course: Course, num_semesters: int) -> int:
    """Use one lower-bound rule in scheduling, repairs and verification."""
    merged = {
        **item,
        "title": course.title,
        "domain": item.get("domain") or course.domain,
        "type": item.get("type") or course.cycle_component,
        "recommended_semester": item.get("recommended_semester") or course.recommended_semester,
    }
    return item_minimum_appropriate_semester(merged, num_semesters)


def credible_professional_lo_by_course(
    project_version: ProjectVersion,
    course_ids: set[int],
    db: Session,
) -> Dict[int, set[str]]:
    """Return programme-specific LO evidence accepted by the final gate."""
    lo_codes = {lo.id: str(lo.lo_code or "") for lo in project_version.learning_outcomes}
    credible_professional: Dict[int, set[str]] = {}
    for match in db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version.id,
        MatchScore.course_id.in_(course_ids or [-1]),
    ).all():
        expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        code = lo_codes.get(match.lo_id, "")
        if code and not code.startswith("LO-GOSO-") and max(float(match.score or 0.0), expert) >= 0.4:
            credible_professional.setdefault(int(match.course_id), set()).add(code)
    return credible_professional


def audit_final_course_admission(schedule: Dict, project_version: ProjectVersion, db: Session) -> Dict:
    """Verify that every persisted real course has auditable admission evidence."""
    constraints = project_version.project.constraints_json or {}
    jurisdiction_kz = str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() == "KZ"
    total_semesters = int(constraints.get("total_semesters", 8) or 8)
    domains = project_domain_terms(project_version, db)
    real_items = [
        (int(semester), item)
        for semester, items in schedule.items()
        for item in items if item.get("course_id") is not None
    ]
    course_ids = {int(item["course_id"]) for _, item in real_items}
    courses = {course.id: course for course in db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()}
    credible_professional = credible_professional_lo_by_course(project_version, course_ids, db)

    scope_pairs = [(str(constraints.get("group_code") or ""), str(constraints.get("direction_code") or ""))]
    if str(constraints.get("program_type") or "").lower() in {"interdisciplinary", "joint"}:
        scope_pairs.append((
            str(constraints.get("secondary_group_code") or ""),
            str(constraints.get("secondary_direction_code") or ""),
        ))

    scoped_ids: set[int] = set()
    if course_ids:
        rows = db.query(EpvoDisciplineNormalized).filter(
            EpvoDisciplineNormalized.approved_course_id.in_(course_ids)
        ).all()
        for row in rows:
            if not epvo_row_matches_education_level(row, constraints.get("education_level")):
                continue
            row_groups = {str(value or "") for value in (row.group_codes or [])}
            row_directions = {str(value or "") for value in (row.direction_codes or [])}
            if any(
                (group and group in row_groups) or (direction and direction in row_directions)
                for group, direction in scope_pairs
            ):
                scoped_ids.add(int(row.approved_course_id))

    violations = []
    for semester, item in real_items:
        course = courses.get(int(item["course_id"]))
        if not course:
            violations.append({"course_id": item["course_id"], "title": item.get("title"), "reason": "missing_course"})
            continue
        code = str(course.course_id or "")
        if code.startswith("GOSO-KZ-") and jurisdiction_kz:
            continue
        reason = None
        minimum_semester = None
        if code.startswith("GOSO-KZ-"):
            reason = "goso_outside_kz_mode"
        elif not education_level_course_allowed(course, constraints.get("education_level")):
            reason = "wrong_education_level"
        elif code.startswith("EPVO-") and course.id not in scoped_ids:
            # Stable machine-readable reason retained for API compatibility.
            reason = "outside_epvo_scope"
        elif not credible_professional.get(course.id):
            reason = "no_credible_professional_lo"
        elif (
            course.id not in scoped_ids
            and not code.startswith("EPVO-")
            and not code.startswith(f"AI-CONFIRMED-{project_version.id}-")
            and not course_domain_matches(course, domains)
        ):
            reason = "outside_project_domain"
        else:
            minimum_semester = minimum_appropriate_semester(item, course, total_semesters)
            if semester < minimum_semester:
                reason = "too_early_for_complexity"
        if reason:
            violations.append({
                "course_id": course.id,
                "title": course.title,
                "semester": semester,
                "reason": reason,
                "minimum_semester": minimum_semester,
                "recommended_semester": item.get("recommended_semester") or course.recommended_semester,
                "selection_method": item.get("selection_method"),
            })
    return {"checked_real_courses": len(real_items), "passed": not violations, "violations": violations}
