"""Late, expert-confirmed replacements for a selected variant.

Keeping this stage outside the main selector makes the order explicit: the
selector chooses candidates first, then this module applies only persisted
human confirmations.  No replacement is inferred here and a missing course
never silently turns into a bridge.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Mapping, Optional, Set

from sqlalchemy.orm import Session

from app.config import settings
from app.models.bridge_module import BridgeModule


def _int_mapping(value: object) -> Dict[int, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        int(source): int(target)
        for source, target in value.items()
        if str(source).isdigit() and str(target).isdigit()
    }


def apply_confirmed_variant_replacements(
    result: List[Dict],
    constraints: Mapping,
    courses: Mapping[int, object],
    prerequisite_ids: Mapping[int, List[int]],
    num_semesters: int,
    replace_redundant_bridges: Callable[[List[Dict], Optional[Set[int]]], List[Dict]],
) -> List[Dict]:
    """Apply course and bridge confirmations without changing credit slots."""
    confirmed_courses = _int_mapping(constraints.get("confirmed_course_replacements"))
    selected_ids = {int(item.get("course_id")) for item in result if item.get("course_id")}
    for index, item in enumerate(result):
        old_id = int(item.get("course_id") or 0)
        replacement_id = confirmed_courses.get(old_id)
        replacement = courses.get(replacement_id)
        if not replacement or replacement_id in selected_ids:
            continue
        selected_ids.discard(old_id)
        selected_ids.add(replacement_id)
        result[index] = {
            "course_id": replacement.id,
            "title": replacement.title,
            "domain": replacement.domain,
            "credits": int(item.get("credits") or replacement.credits or 5),
            "recommended_semester": int(item.get("recommended_semester") or replacement.recommended_semester or 1),
            "latest_semester": int(item.get("latest_semester") or num_semesters),
            "prerequisites": prerequisite_ids.get(replacement.id, []),
            "type": replacement.cycle_component or item.get("type") or "elective",
            "selection_method": "expert_confirmed_course_replacement",
        }

    confirmed_bridges = _int_mapping(constraints.get("confirmed_bridge_replacements"))
    result = replace_redundant_bridges(result, set(confirmed_bridges))
    for index, item in enumerate(result):
        course = courses.get(confirmed_bridges.get(int(item.get("bridge_module_id") or 0)))
        if not course:
            continue
        result[index] = {
            "course_id": course.id,
            "title": course.title,
            "domain": course.domain,
            # Keep the generated plan's credit and semester envelope.
            "credits": int(item.get("credits") or course.credits or 5),
            "recommended_semester": int(item.get("recommended_semester") or course.recommended_semester or 1),
            "latest_semester": int(item.get("latest_semester") or num_semesters),
            "prerequisites": prerequisite_ids.get(course.id, []),
            "type": course.cycle_component or "mandatory",
            "selection_method": "expert_confirmed_ai_bridge_replacement",
        }
    return result


def replace_redundant_bridges_with_real_courses(
    items: List[Dict],
    db: Session,
    courses: Mapping[int, object],
    aggregates: Mapping[int, Mapping[str, object]],
    project_domains: List[str],
    prerequisite_ids: Mapping[int, List[int]],
    protected_bridge_ids: Optional[Set[int]],
    is_project_domain: Callable[[object], bool],
    scope_rank: Callable[[object], int],
    course_role: Callable[[object, List[str]], str],
    priority_rank: Callable[[object], int],
) -> List[Dict]:
    """Replace redundant bridges with equal-credit, evidence-backed courses.

    This is a late assembly operation, not candidate retrieval. Keeping it in
    the replacement module prevents the main variant selector from owning
    bridge persistence, evidence thresholds, and course substitution policy.
    """
    normalized = [dict(item) for item in items]
    protected = protected_bridge_ids or set()
    bridge_ids = {
        int(item.get("bridge_module_id"))
        for item in normalized
        if item.get("bridge_module_id") is not None
    } - protected
    if not bridge_ids:
        return normalized
    bridge_by_id = {
        bridge.id: bridge
        for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids)).all()
    }
    selected_real_ids = {
        int(item["course_id"])
        for item in normalized
        if item.get("course_id") is not None
    }
    covered_codes: Set[str] = set()
    for course_id in selected_real_ids:
        evidence = aggregates.get(course_id, {})
        if float(evidence.get("max") or 0.0) >= float(settings.COVERAGE_THRESHOLD):
            covered_codes.update(evidence.get("lo_codes") or set())

    candidates = [
        course for course in courses.values()
        if course.id not in selected_real_ids
        and is_project_domain(course)
        and scope_rank(course) >= 2
        and course_role(course, project_domains) != "general"
        and all(
            prerequisite_id in selected_real_ids
            for prerequisite_id in prerequisite_ids.get(course.id, [])
        )
        and float(aggregates.get(course.id, {}).get("max") or 0.0) >= 0.4
    ]
    used = set(selected_real_ids)
    for index, item in enumerate(normalized):
        bridge_id = item.get("bridge_module_id")
        if bridge_id is None or int(bridge_id) in protected:
            continue
        bridge = bridge_by_id.get(int(bridge_id))
        if not bridge:
            continue
        target_codes = set(bridge.target_los or [])
        if target_codes and not target_codes.issubset(covered_codes):
            continue
        same_credit = [
            course for course in candidates
            if course.id not in used
            and int(course.credits or 5) == int(item.get("credits") or 5)
        ]
        if not same_credit:
            continue
        same_credit.sort(
            key=lambda course: (
                len(set(aggregates.get(course.id, {}).get("lo_codes") or set()) & target_codes),
                float(aggregates.get(course.id, {}).get("expert") or 0.0),
                float(aggregates.get(course.id, {}).get("max") or 0.0),
                priority_rank(course),
            ),
            reverse=True,
        )
        replacement = same_credit[0]
        used.add(replacement.id)
        normalized[index] = {
            "course_id": replacement.id,
            "title": replacement.title,
            "domain": replacement.domain,
            "credits": int(item.get("credits") or replacement.credits or 5),
            "recommended_semester": replacement.recommended_semester,
            "prerequisites": [],
            "type": replacement.cycle_component or "elective",
            "selection_method": "redundant_bridge_replaced_by_epvo",
        }
    return normalized
