"""Late credit-gap coordinator for schedule repair."""

from __future__ import annotations

import math
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models.bridge_module import BridgeModule
from app.models.project import ProjectVersion
from app.planner.bridge_policy import bridge_module_limit
from app.planner.course_selection import _bridge_item, ensure_credit_bridge_modules


def fill_schedule_credit_gap(
    schedule: Dict[int, List[Dict]],
    project_version: ProjectVersion,
    target_credits: int,
    maximum_credits: int,
    db: Session,
    real_candidates: List[Dict] | None = None,
) -> Dict[int, List[Dict]]:
    """Close a residual schedule gap after late semester repairs."""
    total = sum(int(item.get("credits") or 0) for items in schedule.values() for item in items)
    gap = int(target_credits) - total
    if gap <= 0:
        return schedule
    # Prefer already selected real EPVO courses before creating synthetic
    # bridges.  This keeps the bridge cap meaningful and prevents B/C from
    # silently ending below the requested credit total.
    used_ids = {
        int(item["course_id"])
        for items in schedule.values()
        for item in items
        if item.get("course_id") is not None
    }
    for candidate in sorted(real_candidates or [], key=lambda item: (-int(item.get("credits") or 0), int(item.get("course_id") or 0))):
        if gap <= 0:
            break
        course_id = candidate.get("course_id")
        credits = int(candidate.get("credits") or 0)
        if course_id is None or int(course_id) in used_ids or credits <= 0 or credits > gap:
            continue
        target = min(schedule, key=lambda semester: sum(int(row.get("credits") or 0) for row in schedule[semester]))
        schedule[target].append(dict(candidate, recommended_semester=target, selection_method="credit_gap_real_course"))
        used_ids.add(int(course_id))
        gap -= credits
    if gap <= 0:
        return schedule
    for items in schedule.values():
        for item in reversed(items):
            if gap <= 0 or item.get("bridge_module_id") is None:
                continue
            room = min(7 - int(item.get("credits") or 0), gap)
            if room <= 0:
                continue
            item["credits"] = int(item.get("credits") or 0) + room
            module = db.query(BridgeModule).filter(BridgeModule.id == item["bridge_module_id"]).first()
            # Keep the persisted bridge definition immutable across variants;
            # only this plan item's credit value is being rebalanced.
            gap -= room
    # If the bridge-count budget is already exhausted, an interdisciplinary
    # late rebuild may still leave a small gap although other semesters have
    # spare load.  Reallocate that residual onto existing bridge rows only;
    # never create a sixth bridge and never alter the persisted module credit.
    if gap > 0:
        upper = int((project_version.project.constraints_json or {}).get("max_credits_per_semester", 30)) + 3
        for semester, items in sorted(
            schedule.items(),
            key=lambda pair: sum(int(row.get("credits") or 0) for row in pair[1]),
        ):
            if gap <= 0:
                break
            load = sum(int(row.get("credits") or 0) for row in items)
            bridge_rows = [row for row in items if row.get("bridge_module_id") is not None]
            if not bridge_rows:
                continue
            room = min(gap, max(0, upper - load))
            if room <= 0:
                continue
            bridge_rows[0]["credits"] = int(bridge_rows[0].get("credits") or 0) + room
            gap -= room
    if gap <= 0 or total + gap > int(maximum_credits):
        return schedule
    existing_bridge_ids = {
        int(item.get("bridge_module_id"))
        for items in schedule.values()
        for item in items
        if item.get("bridge_module_id") is not None
    }
    available_bridge_slots = max(0, bridge_module_limit(project_version) - len(existing_bridge_ids))
    if available_bridge_slots <= 0:
        return schedule
    slots_needed = min(available_bridge_slots, max(1, math.ceil(gap / 7)))
    modules = ensure_credit_bridge_modules(project_version, db, gap, slots_needed, desired_count=slots_needed)
    if not modules:
        return schedule
    remaining = gap
    for module in modules:
        if remaining <= 0:
            break
        module.credits = max(3, min(7, math.ceil(remaining / max(1, len(modules)))))
        item = _bridge_item(module)
        item["credits"] = module.credits
        upper = int((project_version.project.constraints_json or {}).get("max_credits_per_semester", 30)) + 3
        eligible = [
            value for value in schedule
            if sum(int(row.get("credits") or 0) for row in schedule[value]) + int(item["credits"]) <= upper
        ]
        if not eligible:
            break
        semester = min(eligible, key=lambda value: sum(int(row.get("credits") or 0) for row in schedule[value]))
        schedule[semester].append(item)
        remaining -= module.credits
    return schedule
