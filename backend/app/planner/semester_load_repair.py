"""Small load-repair primitives used by final semester admission repair."""
from __future__ import annotations

from typing import Dict, List


def balance_semester_with_bridge(
    schedule: Dict[int, List[Dict]],
    semester_number: int,
    course_credit_delta: int,
) -> bool:
    """Absorb a small atomic-course credit delta in an existing bridge."""
    if not course_credit_delta:
        return True
    bridge_options = [
        (index, item)
        for index, item in enumerate(schedule.get(semester_number, []))
        if item.get("bridge_module_id") is not None
        and 3 <= int(item.get("credits") or 0) - course_credit_delta <= 7
    ]
    if not bridge_options:
        return False
    bridge_index, bridge_item = min(
        bridge_options,
        key=lambda row: int(row[1].get("credits") or 0),
    )
    adjusted_bridge = dict(bridge_item)
    adjusted_bridge["credits"] = int(bridge_item.get("credits") or 0) - course_credit_delta
    adjusted_bridge["selection_method"] = (
        f"{bridge_item.get('selection_method') or 'bridge'}"
        "+admission_credit_exchange"
    )
    schedule[semester_number][bridge_index] = adjusted_bridge
    return True
