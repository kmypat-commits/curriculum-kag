"""Pure quota accounting and safety predicates for interdisciplinary variants."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def credits_by_domain(
    items: list[dict],
    *,
    courses: Mapping[int, Any],
    project_domain_share: Callable[[Any, int], float],
    project_domain_index: Callable[[Any], int | None],
    secondary_bridge_ids: set[int],
    core_bridge_id: int | None,
    domain_bridge_codes: Mapping[int, str],
) -> list[float]:
    """Count non-duplicated credits attributed to the two programme domains."""
    values = [0.0, 0.0]
    for item in items:
        course = courses.get(item.get("course_id"))
        if course is not None:
            credits = float(item.get("credits") or 0)
            shares = [project_domain_share(course, index) for index in range(2)]
            if any(shares):
                values[0] += credits * shares[0]
                values[1] += credits * shares[1]
                continue
        index = project_domain_index(course) if course else None
        if index in (0, 1):
            values[index] += float(item.get("credits") or 0)
            continue
        bridge_id = item.get("bridge_module_id")
        credits = float(item.get("credits") or 0)
        if bridge_id in secondary_bridge_ids:
            values[1] += credits
        elif bridge_id == core_bridge_id or str(domain_bridge_codes.get(bridge_id) or "").startswith(
            ("AUTO_BRIDGE_", "QUALITY_BRIDGE_")
        ):
            values[0] += credits / 2.0
            values[1] += credits / 2.0
    return values


def quality_preserved_after_swap(
    trial_items: list[dict],
    *,
    baseline_core_ids: set[int],
    baseline_professional_codes: set[str],
    baseline_lo_scores: Mapping[str, float],
    aggregates: Mapping[int, Mapping[str, Any]],
) -> bool:
    """Reject quota swaps that improve percentages by breaking LO quality."""
    trial_ids = {
        item.get("course_id") for item in trial_items if item.get("course_id") is not None
    }
    if not baseline_core_ids.issubset(trial_ids):
        return False
    trial_codes = {
        str(code)
        for course_id in trial_ids
        for code in (aggregates.get(course_id, {}).get("professional_lo_codes") or set())
    }
    if not baseline_professional_codes.issubset(trial_codes):
        return False
    trial_lo_scores: dict[str, float] = {}
    for course_id in trial_ids:
        for lo_code, score in (aggregates.get(course_id, {}).get("lo_scores") or {}).items():
            trial_lo_scores[str(lo_code)] = max(
                float(trial_lo_scores.get(str(lo_code)) or 0.0), float(score or 0.0)
            )
    return all(
        float(trial_lo_scores.get(lo_code) or 0.0) + 1e-9 >= score
        for lo_code, score in baseline_lo_scores.items()
    )


def protected_quota_course_ids(
    items: list[dict],
    *,
    courses: Mapping[int, Any],
    aggregates: Mapping[int, Mapping[str, Any]],
    constraints: Mapping[str, Any],
    project_domains: list[str],
    curriculum_role: Callable[[Any, list[str]], str],
) -> set[int]:
    """Return courses that a quota repair must never replace."""
    selected_ids = {item.get("course_id") for item in items if item.get("course_id") is not None}
    prerequisite_ids = {
        prerequisite_id
        for item in items
        for prerequisite_id in (item.get("prerequisites") or [])
        if prerequisite_id in selected_ids
    }
    expert_confirmed_ids = {
        int(course_id)
        for mapping_name in ("confirmed_bridge_replacements", "confirmed_course_replacements")
        for course_id in (constraints.get(mapping_name) or {}).values()
        if str(course_id).isdigit()
    }
    quota_reserve_ids = {
        int(item["course_id"])
        for item in items
        if item.get("course_id") is not None and item.get("domain_quota_reserve")
    }
    competency_ids = {
        int(item["course_id"])
        for item in items
        if item.get("course_id") is not None and item.get("competency_required")
    }
    core_ids = {
        int(item["course_id"])
        for item in items
        if item.get("course_id") is not None
        and courses.get(item["course_id"]) is not None
        and curriculum_role(courses[item["course_id"]], project_domains) == "core"
    }
    lo_sources: dict[str, set[int]] = {}
    for item in items:
        course_id = item.get("course_id")
        evidence = aggregates.get(course_id, {})
        for lo_code in evidence.get("professional_lo_codes") or set():
            lo_sources.setdefault(str(lo_code), set()).add(int(course_id))
    unique_lo_ids = {
        course_id
        for source_ids in lo_sources.values()
        if len(source_ids) == 1
        for course_id in source_ids
    }
    return (
        prerequisite_ids
        | expert_confirmed_ids
        | quota_reserve_ids
        | competency_ids
        | core_ids
        | unique_lo_ids
    )
