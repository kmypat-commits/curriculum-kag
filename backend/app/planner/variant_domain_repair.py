"""Domain-quota repair for interdisciplinary curriculum variants."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import partial
from itertools import combinations
from typing import Any, Dict, List

from app.models.bridge_module import BridgeModule
from app.planner.course_policy import course_curriculum_role as _course_curriculum_role
from app.planner.scheduler_domain_rules import course_domain_matches as _course_domain_matches
from app.planner.scheduler_utils import title_key as _title_key
from app.planner.variant_quota import (
    build_missing_domain_bundle as _build_missing_domain_bundle,
    credits_by_domain as _credits_by_domain,
    protected_quota_course_ids as _protected_quota_course_ids,
    quality_preserved_after_swap as _quality_preserved_after_swap,
    required_domain_credits as _required_domain_credits,
)
from app.planner.variant_policy import course_role_rank as _course_role_rank


def rebalance_domain_quotas(
    items: list[dict],
    *,
    interdisciplinary: bool,
    constraints: Mapping[str, Any],
    quota_total_credits: int,
    min_domain_percent: list[int],
    secondary_bridges: Sequence[Any],
    core_bridge: Any | None,
    db: Any,
    courses: Mapping[int, Any],
    project_domain_share: Callable[[Any, int], float],
    project_domain_index: Callable[[Any], int | None],
    aggregates: Mapping[int, Mapping[str, Any]],
    project_domains: Sequence[str],
    prereq_ids_by_course: Mapping[int, Sequence[int]],
    domain_quota_candidates: Callable[[int], Sequence[Any]],
    priority_rank: Callable[[Any], int],
    epvo_domain_index: Mapping[int, int],
) -> list[dict]:
    if not interdisciplinary:
        return items
    domain_quota_tolerance = max(
        0.0, float(constraints.get("domain_quota_tolerance_credits", 3) or 0)
    )
    required = _required_domain_credits(
        total_credits=int(
            constraints.get("total_credits", quota_total_credits) or quota_total_credits
        ),
        minimum_percentages=min_domain_percent,
        regulatory_credits=sum(
            int(item.get("credits") or 0)
            for item in items
            if item.get("regulatory_required")
        ),
        tolerance=domain_quota_tolerance,
    )
    if not any(required):
        return items
    normalized = [dict(item) for item in items]

    secondary_bridge_ids = {bridge.id for bridge in secondary_bridges}
    core_bridge_id = core_bridge.id if core_bridge is not None else None
    domain_bridge_codes = {
        bridge.id: str(bridge.course_id or "")
        for bridge in [*(secondary_bridges or []), *([core_bridge] if core_bridge is not None else [])]
    }
    bridge_ids_in_plan = {
        int(item.get("bridge_module_id"))
        for item in normalized
        if item.get("bridge_module_id") is not None
    }
    if bridge_ids_in_plan:
        domain_bridge_codes.update({
            bridge.id: str(bridge.course_id or "")
            for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids_in_plan)).all()
        })

    credits_by_domain = partial(
        _credits_by_domain,
        courses=courses,
        project_domain_share=project_domain_share,
        project_domain_index=project_domain_index,
        secondary_bridge_ids=secondary_bridge_ids,
        core_bridge_id=core_bridge_id,
        domain_bridge_codes=domain_bridge_codes,
    )

    selected_ids = lambda: {
        item.get("course_id")
        for item in normalized
        if item.get("course_id") is not None
    }

    baseline_course_ids = selected_ids()
    baseline_courses = [courses[course_id] for course_id in baseline_course_ids if course_id in courses]
    baseline_core_ids = {
        int(course.id)
        for course in baseline_courses
        if _course_curriculum_role(course, project_domains) == "core"
    }
    baseline_professional_codes = {
        str(code)
        for course_id in baseline_course_ids
        for code in (aggregates.get(course_id, {}).get("professional_lo_codes") or set())
    }
    baseline_lo_scores = {}
    for course_id in baseline_course_ids:
        for lo_code, score in (aggregates.get(course_id, {}).get("lo_scores") or {}).items():
            baseline_lo_scores[str(lo_code)] = max(
                float(baseline_lo_scores.get(str(lo_code)) or 0.0), float(score or 0.0)
            )

    quality_preserved = partial(
        _quality_preserved_after_swap,
        baseline_core_ids=baseline_core_ids,
        baseline_professional_codes=baseline_professional_codes,
        baseline_lo_scores=baseline_lo_scores,
        aggregates=aggregates,
    )
    protected_ids = partial(
        _protected_quota_course_ids,
        courses=courses,
        aggregates=aggregates,
        constraints=constraints,
        project_domains=project_domains,
        curriculum_role=_course_curriculum_role,
    )

    for domain_index in (0, 1):
        guard = 0
        # A 40% quota may require more than twenty 3-credit swaps. Stop
        # only after the plan-sized safety limit or when no valid swap is
        # available, not at an arbitrary fixed count.
        guard_limit = max(20, len(normalized) * 2)
        while credits_by_domain(normalized)[domain_index] < required[domain_index] and guard < guard_limit:
            guard += 1
            current = credits_by_domain(normalized)
            ids = selected_ids()
            titles = {_title_key(item.get("title")) for item in normalized if item.get("title")}
            candidates = [
                course for course in domain_quota_candidates(domain_index)
                if course.id not in ids
                and _title_key(course.title) not in titles
                and all(pre_id in ids for pre_id in prereq_ids_by_course.get(course.id, []))
            ][:80]
            swapped = False
            protected = protected_ids(normalized)
            for candidate in candidates:
                candidate_credits = int(candidate.credits or 5)
                replaceable = []
                for index, item in enumerate(normalized):
                    course = courses.get(item.get("course_id"))
                    replace_domain = project_domain_index(course) if course else None
                    can_reduce_replace_domain = (
                        replace_domain not in (0, 1)
                        or current[replace_domain] - candidate_credits >= required[replace_domain]
                    )
                    if (
                        course
                        and not item.get("regulatory_required")
                        and item.get("course_id") not in protected
                        and replace_domain != domain_index
                        and int(item.get("credits") or 0) == candidate_credits
                        and can_reduce_replace_domain
                    ):
                        replaceable.append((index, item, course))
                if not replaceable:
                    continue
                replaceable.sort(
                    key=lambda row: (
                        _course_role_rank(row[2], project_domains),
                        priority_rank(row[2]),
                        int(row[1].get("recommended_semester") or 99),
                    )
                )
                replace_index, _old_item, _old_course = replaceable[0]
                replacement_item = {
                    "course_id": candidate.id,
                    "title": candidate.title,
                    "domain": candidate.domain,
                    "credits": candidate.credits or 5,
                    "recommended_semester": candidate.recommended_semester,
                    "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                    "type": candidate.cycle_component or "mandatory",
                    "selection_method": "domain_quota_rebalance",
                }
                trial = [
                    replacement_item if index == replace_index else item
                    for index, item in enumerate(normalized)
                ]
                if not quality_preserved(trial):
                    continue
                normalized[replace_index] = replacement_item
                swapped = True
                break
            if not swapped:
                # Credit values in EPVO are heterogeneous (3/4/5). A
                # strict one-for-one swap can stop below quota even when
                # enough strong courses exist. Try a bounded 1–3 course
                # exchanges with exactly the same total credits.
                replaceable_all = []
                for index, item in enumerate(normalized):
                    course = courses.get(item.get("course_id"))
                    replace_domain = project_domain_index(course) if course else None
                    if (
                        course
                        and not item.get("regulatory_required")
                        and item.get("course_id") not in protected
                        and replace_domain != domain_index
                    ):
                        replaceable_all.append((index, item, course))
                replacement_groups: Dict[int, List[tuple]] = {}
                for size in (1, 2, 3):
                    for group in combinations(replaceable_all, size):
                        group_credits = sum(int(row[1].get("credits") or 0) for row in group)
                        removed = [
                            sum(
                                int(row[1].get("credits") or 0)
                                * project_domain_share(row[2], index)
                                for row in group
                            )
                            for index in range(2)
                        ]
                        if all(
                            current[index] - removed[index] >= required[index]
                            for index in range(2)
                            if index != domain_index
                        ):
                            replacement_groups.setdefault(group_credits, []).append(group)
                candidate_groups = [*( (course,) for course in candidates )]
                # Keep the exact exchange search bounded. The candidate
                # list is already ranked by LO/expert/scope evidence; a
                # 16-item frontier captures the high-quality options
                # without turning a large EPVO programme into an O(n^4)
                # planner step.
                bounded_candidates = candidates[:16]
                candidate_groups.extend(combinations(bounded_candidates, 2))
                candidate_groups.extend(combinations(bounded_candidates, 3))
                for candidate_group in candidate_groups:
                    group_credits = sum(int(course.credits or 5) for course in candidate_group)
                    replacements = replacement_groups.get(group_credits)
                    if not replacements:
                        continue
                    replacement_group = min(
                        replacements,
                        key=lambda group: sum(
                            _course_role_rank(row[2], project_domains) * 1000
                            + priority_rank(row[2])
                            for row in group
                        ),
                    )
                    replacement_indexes = {row[0] for row in replacement_group}
                    trial = [
                        item for index, item in enumerate(normalized)
                        if index not in replacement_indexes
                    ] + [
                        {
                            "course_id": candidate.id,
                            "title": candidate.title,
                            "domain": candidate.domain,
                            "credits": candidate.credits or 5,
                            "recommended_semester": candidate.recommended_semester,
                            "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                            "type": candidate.cycle_component or "mandatory",
                            "selection_method": "domain_quota_group_rebalance",
                        }
                        for candidate in candidate_group
                    ]
                    if not quality_preserved(trial):
                        continue
                    for replace_index, _item, _course in sorted(
                        replacement_group, key=lambda row: row[0], reverse=True
                    ):
                        normalized.pop(replace_index)
                    for candidate in candidate_group:
                        normalized.append({
                            "course_id": candidate.id,
                            "title": candidate.title,
                            "domain": candidate.domain,
                            "credits": candidate.credits or 5,
                            "recommended_semester": candidate.recommended_semester,
                            "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                            "type": candidate.cycle_component or "mandatory",
                            "selection_method": "domain_quota_group_rebalance",
                        })
                    swapped = True
                    break
            if not swapped:
                def missing_domain_bundle(course_id: int, visiting: set | None = None):
                    return _build_missing_domain_bundle(
                        course_id,
                        selected_ids=ids,
                        courses=courses,
                        prerequisite_ids_by_course=prereq_ids_by_course,
                        target_domain=domain_index,
                        project_domain_index=project_domain_index,
                        epvo_domain_index=epvo_domain_index,
                        project_domains=project_domains,
                        course_domain_matches=_course_domain_matches,
                        title_key=_title_key,
                        visiting=visiting,
                    )

                bundle_candidates = []
                for candidate in domain_quota_candidates(domain_index):
                    if candidate.id in ids or _title_key(candidate.title) in titles:
                        continue
                    candidate_bundle = missing_domain_bundle(candidate.id)
                    if not candidate_bundle or len(candidate_bundle) > 4:
                        continue
                    bundle_credits = sum(int(value.credits or 5) for value in candidate_bundle)
                    target_credits = sum(
                        int(value.credits or 5)
                        for value in candidate_bundle
                        if project_domain_index(value) == domain_index
                    )
                    if bundle_credits <= 0 or bundle_credits > 24 or target_credits <= 0:
                        continue
                    bundle_candidates.append((candidate_bundle, bundle_credits, target_credits))
                    if len(bundle_candidates) >= 80:
                        break

                replaceable_all = []
                for index, item in enumerate(normalized):
                    course = courses.get(item.get("course_id"))
                    replace_domain = project_domain_index(course) if course else None
                    if (
                        course
                        and not item.get("regulatory_required")
                        and item.get("course_id") not in protected
                        and replace_domain != domain_index
                    ):
                        replaceable_all.append((index, item, course))
                replaceable_all.sort(key=lambda row: (
                    _course_role_rank(row[2], project_domains),
                    priority_rank(row[2]),
                    int(row[1].get("recommended_semester") or 99),
                ))
                replaceable_all = replaceable_all[:16]
                replacement_groups = {}
                for size in (1, 2, 3, 4):
                    for group in combinations(replaceable_all, size):
                        group_credits = sum(int(row[1].get("credits") or 0) for row in group)
                        other_domain = project_domain_index(group[0][2])
                        if (
                            other_domain not in (0, 1)
                            or current[other_domain] - group_credits >= required[other_domain]
                        ):
                            replacement_groups.setdefault(group_credits, group)
                for candidate_bundle, bundle_credits, target_credits in bundle_candidates:
                    replacement_group = replacement_groups.get(bundle_credits)
                    if not replacement_group:
                        continue
                    replacement_indexes = {row[0] for row in replacement_group}
                    trial = [
                        item for index, item in enumerate(normalized)
                        if index not in replacement_indexes
                    ] + [
                        {
                            "course_id": candidate.id,
                            "title": candidate.title,
                            "domain": candidate.domain,
                            "credits": candidate.credits or 5,
                            "recommended_semester": candidate.recommended_semester,
                            "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                            "type": candidate.cycle_component or "mandatory",
                            "selection_method": "domain_quota_prerequisite_bundle",
                        }
                        for candidate in candidate_bundle
                    ]
                    if not quality_preserved(trial):
                        continue
                    for replace_index, _item, _course in sorted(
                        replacement_group, key=lambda row: row[0], reverse=True
                    ):
                        normalized.pop(replace_index)
                    for candidate in candidate_bundle:
                        normalized.append({
                            "course_id": candidate.id,
                            "title": candidate.title,
                            "domain": candidate.domain,
                            "credits": candidate.credits or 5,
                            "recommended_semester": candidate.recommended_semester,
                            "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                            "type": candidate.cycle_component or "mandatory",
                            "selection_method": "domain_quota_prerequisite_bundle",
                        })
                    swapped = True
                    break
            if not swapped:
                break
    return normalized


def reserve_domain_quota(
    domain_index: int,
    *,
    selected: dict[int, dict],
    total: int,
    maximum: int,
    quota_total_credits: int,
    minimum_percentages: list[int],
    candidate_ids: Sequence[int],
    courses: Mapping[int, Any],
    project_domain_share: Callable[[Any, int], float],
    bundle_for_course: Callable[[int], Sequence[dict]],
    selected_domain_credit_total: Callable[[int], int],
) -> int:
    """Reserve prerequisite bundles needed to meet one domain quota."""
    regulatory_selected_credits = sum(
        int(item.get("credits") or 0)
        for item in selected.values()
        if item.get("regulatory_required")
    )
    quota_base = max(0, quota_total_credits - regulatory_selected_credits)
    required = int(quota_base * minimum_percentages[domain_index] / 100)
    if required <= 0:
        return total
    domain_candidates = [
        course_id
        for course_id in candidate_ids
        if course_id in courses
        and project_domain_share(courses[course_id], domain_index) > 0.0
    ]
    for course_id in domain_candidates:
        if selected_domain_credit_total(domain_index) >= required:
            break
        additions = list(
            {
                item["course_id"]: item
                for item in bundle_for_course(course_id)
                if item["course_id"] not in selected
            }.values()
        )
        addition_credits = sum(item["credits"] for item in additions)
        if not additions or total + addition_credits > maximum:
            continue
        for item in additions:
            reserved = dict(item)
            reserved["domain_quota_reserve"] = domain_index + 1
            reserved["selection_method"] = "domain_quota_reserve"
            selected[reserved["course_id"]] = reserved
        total = sum(item["credits"] for item in selected.values())
    return total
