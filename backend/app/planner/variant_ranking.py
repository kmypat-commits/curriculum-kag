"""Deterministic ranking primitives for curriculum-plan variants."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


def ranked_unique_candidate_ids(
    candidate_ids: Iterable[int],
    *,
    rank: Callable[[int], tuple],
    title_for: Callable[[int], str],
    limit: int = 100,
) -> list[int]:
    """Rank candidates and retain one canonical representative per title."""
    result: list[int] = []
    seen_titles: set[str] = set()
    for course_id in sorted(candidate_ids, key=rank, reverse=True):
        title = title_for(course_id)
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        result.append(course_id)
        if len(result) >= limit:
            break
    return result


def rank_variant_candidates(
    candidate_ids: Iterable[int],
    *,
    aggregates: dict[int, dict[str, Any]],
    courses: dict[int, Any],
    prerequisite_ids_by_course: dict[int, list[int]],
    course_depth: Callable[[int], int],
    role_rank: Callable[[Any], int],
    scope_rank: Callable[[Any], int],
    priority_rank: Callable[[Any], int],
    semester_stability_rank: Callable[[Any], int],
    variant_type: str,
    project_domains: Iterable[str] = (),
    title_for: Callable[[int], str],
    limit: int = 100,
) -> list[int]:
    """Rank a bounded variant frontier without owning domain policy.

    The planner supplies the evidence and policy callbacks because those are
    programme-specific.  Keeping the deterministic tuple and uniqueness rule
    here makes retrieval/ranking testable independently from semester repair
    and final plan assembly.
    """
    def rank(course_id: int) -> tuple:
        return variant_candidate_key(
            course_id,
            aggregates=aggregates,
            courses=courses,
            prerequisite_ids_by_course=prerequisite_ids_by_course,
            course_depth=course_depth,
            role_rank=role_rank,
            scope_rank=scope_rank,
            priority_rank=priority_rank,
            semester_stability_rank=semester_stability_rank,
            variant_type=variant_type,
            project_domains=project_domains,
        )

    return ranked_unique_candidate_ids(
        candidate_ids,
        rank=rank,
        title_for=title_for,
        limit=limit,
    )


def variant_candidate_key(
    course_id: int,
    *,
    aggregates: dict[int, dict[str, Any]],
    courses: dict[int, Any],
    prerequisite_ids_by_course: dict[int, list[int]],
    course_depth: Callable[[int], int],
    role_rank: Callable[[Any], int],
    scope_rank: Callable[[Any], int],
    priority_rank: Callable[[Any], int],
    semester_stability_rank: Callable[[Any], int],
    variant_type: str,
    project_domains: Iterable[str] = (),
) -> tuple:
    """Return the canonical sort key used by frontier ranking and assembly."""
    data = aggregates[course_id]
    course = courses.get(course_id)
    credits = max(1, int(getattr(course, "credits", 1) or 1))
    semester_preference = -int(getattr(course, "recommended_semester", 99) or 99)
    common = (
        role_rank(course),
        scope_rank(course),
        priority_rank(course),
        semester_stability_rank(course),
        semester_preference,
    )
    depth = course_depth(course_id)
    prereq_count = len(prerequisite_ids_by_course.get(course_id, []))
    if variant_type == "B":
        return common + (-depth, -prereq_count, data["max"], -credits, course.id)
    if variant_type == "C":
        domain = str(getattr(course, "domain", "") or "").lower()
        domains = {str(value or "").lower() for value in project_domains}
        domain_bonus = int(any(value and (value in domain or domain in value) for value in domains))
        return common + (-prereq_count, domain_bonus, data["sum"] / credits, -depth, -course.id)
    return common + (len(data["los"]), data["sum"], data["max"], -depth, -course.id)
