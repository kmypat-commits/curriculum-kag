"""Orchestration helpers for executing requested planner variants."""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any


def run_requested_variants(
    requested_variants: Iterable[str],
    *,
    build_variant: Callable[[str], dict[str, Any]],
    assert_live: Callable[[], None],
    set_stage: Callable[[str, int], None],
    stage_progress: dict[str, int],
    completed_progress: dict[str, int],
    results: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    """Build each requested variant and return results plus timings."""
    variants = results if results is not None else {}
    timings: dict[str, float] = {}
    for variant_type in requested_variants:
        assert_live()
        started = time.perf_counter()
        set_stage(f"variant_{variant_type}_start", stage_progress[variant_type])
        result = build_variant(variant_type)
        assert_live()
        variants[variant_type] = result
        timings[f"variant_{variant_type}"] = round(time.perf_counter() - started, 2)
        set_stage(f"variant_{variant_type}", completed_progress[variant_type])
    return variants, timings
