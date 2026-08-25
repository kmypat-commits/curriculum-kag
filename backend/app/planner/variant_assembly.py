"""Small, side-effect-free assembly primitives for curriculum variants."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Dict, Iterable, Mapping


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


def assemble_foundation_frontier(
    candidate_ids: Iterable[int],
    *,
    selected: Dict[int, Dict],
    bundle_for_course: Callable[[int], list[Dict]],
    rank_key: Callable[[int], tuple],
    foundation_target: int,
    maximum_credits: int,
) -> int:
    """Add ranked zero-depth foundation roots until the target is reached.

    The planner supplies the project-specific candidate and prerequisite
    bundle callbacks.  This helper only owns the deterministic assembly loop,
    preserving the historical rule that the root item is committed while the
    bundle builder decides whether its prerequisites are admissible.
    """
    total = 0
    for course_id in sorted(candidate_ids, key=rank_key, reverse=True):
        bundle = bundle_for_course(course_id)
        item = bundle[-1] if bundle else None
        if not item or total + int(item.get("credits") or 0) > maximum_credits:
            continue
        selected[course_id] = item
        total += int(item.get("credits") or 0)
        if total >= foundation_target:
            break
    return total


def selected_domain_credits(
    selected: Mapping[int, Dict],
    *,
    courses: Mapping[int, Any],
    domain_index: int,
    domain_share: Callable[[Any, int], float],
) -> int:
    """Return non-duplicated selected credits attributed to one domain."""
    value = 0.0
    for item in selected.values():
        course = courses.get(item.get("course_id"))
        if course is not None:
            value += int(item.get("credits") or 0) * domain_share(course, domain_index)
    return int(round(value))


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


def top_up_with_real_epvo_courses(
    items: list[Dict],
    *,
    target_credits: int,
    maximum_credits: int,
    courses: Mapping[int, Any],
    prerequisite_ids_by_course: Mapping[int, list[int]],
    aggregates: Mapping[int, Mapping[str, Any]],
    num_semesters: int,
    title_key: Callable[[Any], str],
    is_project_domain: Callable[[Any], bool],
    scope_rank: Callable[[Any], int],
    priority_rank: Callable[[Any], int],
    course_depth: Callable[[int], int],
    course_matches_scope_theme: Callable[[Any], bool],
    has_strong_exact_scope_evidence: Callable[[Any], bool],
    unique_items_by_title: Callable[[list[Dict]], list[Dict]],
    admit_real_courses: Callable[[list[Dict]], list[Dict]],
) -> list[Dict]:
    """Fill a credit gap with real scoped EPVO courses before bridges.

    Candidate retrieval and admission are callbacks so this primitive does
    not know project policy.  It only owns the deterministic assembly order:
    unique/admitted items first, then unused EPVO courses with professional LO
    evidence, bounded prerequisites and available credit capacity.
    """
    normalized = unique_items_by_title(admit_real_courses(items))
    total_now = sum(int(item.get("credits") or 0) for item in normalized)
    if total_now >= target_credits:
        return normalized
    selected_ids = {
        int(item.get("course_id")) for item in normalized if item.get("course_id")
    }
    selected_titles = {
        title_key(item.get("title")) for item in normalized if item.get("title")
    }
    candidates = []
    for course in courses.values():
        if course.id in selected_ids or title_key(course.title) in selected_titles:
            continue
        if not str(course.course_id or "").startswith("EPVO-"):
            continue
        if not is_project_domain(course) or scope_rank(course) <= 0:
            continue
        if not course_matches_scope_theme(course) and not has_strong_exact_scope_evidence(course):
            continue
        if course_depth(course.id) >= num_semesters:
            continue
        prerequisites = prerequisite_ids_by_course.get(course.id, [])
        if any(pre_id not in selected_ids for pre_id in prerequisites):
            continue
        evidence = aggregates.get(course.id, {})
        if not evidence.get("professional_lo_codes"):
            continue
        candidates.append(course)
    candidates.sort(key=lambda course: (
        -scope_rank(course),
        -priority_rank(course),
        -float(aggregates.get(course.id, {}).get("max") or 0.0),
        course.recommended_semester or 99,
        course.id,
    ))
    for course in candidates:
        credits = int(course.credits or 5)
        if total_now + credits > maximum_credits:
            continue
        normalized.append({
            "course_id": course.id,
            "title": course.title,
            "domain": course.domain,
            "credits": credits,
            "recommended_semester": course.recommended_semester,
            "prerequisites": prerequisite_ids_by_course.get(course.id, []),
            "type": course.cycle_component or "elective",
            "epvo_exact_scope": scope_rank(course) >= 3,
            "selection_method": "real_epvo_credit_top_up",
        })
        selected_ids.add(course.id)
        selected_titles.add(title_key(course.title))
        total_now += credits
        if total_now >= target_credits:
            break
    return admit_real_courses(normalized)
