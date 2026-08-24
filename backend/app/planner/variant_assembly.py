"""Small, side-effect-free assembly primitives for curriculum variants."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Dict, Iterable


def add_bundle_if_fits(
    selected: Dict[int, Dict],
    bundle: Iterable[Dict],
    maximum_credits: int,
) -> tuple[int, bool]:
    """Add a prerequisite bundle atomically when it fits the credit envelope."""
    additions = {
        item["course_id"]: item
        for item in bundle
        if item.get("course_id") is not None and item["course_id"] not in selected
    }
    current = sum(int(item.get("credits") or 0) for item in selected.values())
    addition_credits = sum(int(item.get("credits") or 0) for item in additions.values())
    if not additions or current + addition_credits > maximum_credits:
        return current, False
    selected.update(additions)
    return current + addition_credits, True


def build_prerequisite_bundle(
    course_id: int,
    *,
    courses: dict[int, Any],
    prerequisite_ids_by_course: dict[int, list[int]],
    selected: dict[int, Dict],
    is_project_domain: Callable[[Any], bool],
    scope_rank: Callable[[Any], int],
    visiting: set[int] | None = None,
) -> list[Dict]:
    """Assemble one course and its admissible prerequisite closure.

    Domain admission remains a callback owned by the planner.  The assembly
    primitive itself only handles cycle protection, already-selected courses,
    and atomic item shape; it never invents a cross-domain prerequisite.
    """
    visiting = visiting or set()
    if course_id in visiting or course_id in selected or course_id not in courses:
        return []
    course = courses[course_id]
    if not is_project_domain(course):
        return []
    result: list[Dict] = []
    for prerequisite_id in prerequisite_ids_by_course.get(course_id, []):
        prerequisite_bundle = build_prerequisite_bundle(
            prerequisite_id,
            courses=courses,
            prerequisite_ids_by_course=prerequisite_ids_by_course,
            selected=selected,
            is_project_domain=is_project_domain,
            scope_rank=scope_rank,
            visiting=visiting | {course_id},
        )
        if prerequisite_id not in selected and not prerequisite_bundle:
            return []
        result.extend(prerequisite_bundle)
    if course_id not in selected and all(
        item["course_id"] != course_id for item in result
    ):
        result.append({
            "course_id": course.id,
            "title": course.title,
            "domain": course.domain,
            "credits": course.credits or 5,
            "recommended_semester": course.recommended_semester,
            "prerequisites": prerequisite_ids_by_course.get(course.id, []),
            "type": course.cycle_component or "mandatory",
            "epvo_exact_scope": scope_rank(course) >= 3,
        })
    return result
