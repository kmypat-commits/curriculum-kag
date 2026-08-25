"""Small, deterministic repairs applied after variant assembly.

The public variant strategy remains the orchestration layer; credit repair is
kept here so bridge creation and real-course top-up can be tested separately.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def top_up_with_credit_bridges(
    items: list[dict],
    *,
    allow_new_courses: bool,
    target: int,
    maximum: int,
    max_new_courses: int,
    variant_type: str,
    version: Any,
    db: Any,
    top_up_real_epvo_callback: Callable[[list[dict]], list[dict]],
    ensure_credit_bridge_modules: Callable[..., list[Any]],
    bridge_item: Callable[[Any], dict],
) -> list[dict]:
    """Fill a credit deficit with real EPVO courses, then bounded bridges.

    The callback is passed explicitly because the real-course top-up is bound
    later by the strategy after scope and prerequisite indexes are available.
    """
    if not allow_new_courses:
        return items
    normalized = top_up_real_epvo_callback(items)
    total_now = sum(int(item.get("credits") or 0) for item in normalized)
    if total_now >= target:
        return normalized

    current_bridge_count = sum(
        1 for item in normalized if item.get("bridge_module_id") is not None
    )
    remaining_slots = max(0, max_new_courses - current_bridge_count)
    # A late duplicate/prerequisite cleanup can reopen a small exact-credit gap
    # after all configured bridge slots are occupied.
    if remaining_slots <= 0 and 0 < target - total_now <= 3:
        remaining_slots = 1
    if remaining_slots <= 0:
        return normalized

    auto_modules = ensure_credit_bridge_modules(
        version,
        db,
        min(maximum - total_now, target - total_now),
        remaining_slots,
        desired_count=remaining_slots if variant_type == "C" else None,
    )
    result = list(normalized)
    for module in auto_modules:
        credits = int(module.credits or 5)
        if total_now + credits > maximum:
            continue
        bridge = bridge_item(module)
        bridge["credits"] = credits
        result.append(bridge)
        total_now += credits
        if total_now >= target:
            break
    return result
