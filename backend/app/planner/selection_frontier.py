from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Mapping, Set

from app.models.course import Course


def build_domain_quota_frontier(
    courses: Mapping[int, Course],
    aggregates: Mapping[int, Mapping[str, object]],
    candidate_ids: Iterable[int],
    secondary_candidate_ids: Iterable[int],
    domain_share: Callable[[Course, int], float],
    *,
    per_domain_limit: int = 160,
) -> List[Course]:
    """Build the bounded, evidence-ranked catalogue frontier for quota repair.

    The selector already performs scope, level and evidence admission. Quota
    repair should search that frontier plus a small domain-specific recovery
    slice, rather than scanning the complete catalogue for every variant.
    """
    frontier_ids: Set[int] = set(candidate_ids) | set(secondary_candidate_ids)
    for domain_index in (0, 1):
        domain_candidates = [
            course
            for course in courses.values()
            if course.id in aggregates and domain_share(course, domain_index) > 0.0
        ]
        domain_candidates.sort(
            key=lambda course: (
                -float(aggregates.get(course.id, {}).get("expert") or 0.0),
                -float(aggregates.get(course.id, {}).get("max") or 0.0),
                course.id,
            )
        )
        frontier_ids.update(course.id for course in domain_candidates[:per_domain_limit])

    return [courses[course_id] for course_id in frontier_ids if course_id in courses]
