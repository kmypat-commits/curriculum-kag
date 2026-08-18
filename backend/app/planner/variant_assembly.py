"""Small, side-effect-free assembly primitives for curriculum variants."""
from __future__ import annotations

from typing import Dict, Iterable


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
