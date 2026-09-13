"""Checks executed at the scheduler publication boundary."""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from app.planner.admission import audit_final_course_admission
from app.planner.scheduler_domain_rules import find_invalid_project_domain_courses
from app.models.course import Course


def audit_final_schedule_boundary(
    schedule: Mapping[int, Sequence[Mapping[str, Any]]],
    *,
    db: Any,
    project_version: Any,
    project_domains: Sequence[str],
    declared_secondary_domain: str,
    is_project_domain: Callable[[Any], bool],
    is_general_course: Callable[[Any], bool],
) -> dict[str, Any]:
    """Run the non-mutating checks required before plan publication."""
    invalid_domain_courses = find_invalid_project_domain_courses(
        schedule,
        db,
        project_domains,
        declared_secondary_domain,
        is_project_domain,
        is_general_course=is_general_course,
    )
    return {
        "invalid_domain_courses": invalid_domain_courses,
        "admission": audit_final_course_admission(schedule, project_version, db),
    }


def late_schedule_snapshot(
    schedule: Mapping[int, Sequence[Mapping[str, Any]]],
    *,
    db: Any,
    num_semesters: int,
    minimum_semester: Callable[[Mapping[str, Any], Any, int], int],
) -> dict[int, dict[str, Any]]:
    """Create a compact diagnostic snapshot for the final semesters."""
    snapshot: dict[int, dict[str, Any]] = {}
    for semester, items in schedule.items():
        semester_number = int(semester)
        if semester_number < max(1, num_semesters - 2):
            continue
        snapshot[semester_number] = {
            "credits": sum(int(item.get("credits") or 0) for item in items),
            "items": [
                {
                    "title": item.get("title"),
                    "credits": int(item.get("credits") or 0),
                    "minimum": (
                        minimum_semester(item, db.get(Course, int(item["course_id"])), num_semesters)
                        if item.get("course_id") is not None
                        and db.get(Course, int(item["course_id"])) is not None
                        else None
                    ),
                    "regulatory": bool(item.get("regulatory_required")),
                    "competency": bool(item.get("competency_required")),
                }
                for item in items
            ],
        }
    return snapshot
