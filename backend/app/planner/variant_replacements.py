"""Late, expert-confirmed replacements for a selected variant.

Keeping this stage outside the main selector makes the order explicit: the
selector chooses candidates first, then this module applies only persisted
human confirmations.  No replacement is inferred here and a missing course
never silently turns into a bridge.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Mapping, Optional, Set


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
