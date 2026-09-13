"""Pure request and publication rules shared by planner build routes."""

from __future__ import annotations

import hashlib
import json


def build_request_hash(project_version_id: int, variants: object) -> str:
    """Return a stable hash of the explicit build command."""
    canonical = json.dumps(
        {"project_version_id": int(project_version_id), "variants": variants},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_requested_variants(variants: object) -> list[str]:
    """Normalize the UI/API selector; the standard build creates A only."""
    if variants in (None, ""):
        requested = ["A"]
    elif variants == "all":
        requested = ["A", "B", "C"]
    elif isinstance(variants, str):
        requested = [item.strip().upper() for item in variants.split(",")]
    else:
        requested = [str(item).strip().upper() for item in variants]
    return list(dict.fromkeys(item for item in requested if item in {"A", "B", "C"}))


def must_reject_variant(verification: dict | None) -> bool:
    """Return whether a generated variant is unsafe to persist."""
    verification = verification or {}
    quality_reasons = {
        str(item.get("reason"))
        for item in (verification.get("quality_violations") or [])
        if isinstance(item, dict)
    }
    blocking_quality_reasons = {
        "semester_appropriateness",
        "missing_core_competency_blocks",
        "bridge_module_limit_exceeded",
    }
    return bool(
        not verification.get("feasible")
        or int(verification.get("hard_violation_count") or 0) > 0
        or "lo_without_real_course" in quality_reasons
        or quality_reasons.intersection(blocking_quality_reasons)
    )


def activate_only_plan(plan_rows: list, active_plan_id: int | None):
    """Mark exactly one plan active and return it."""
    active_plan = None
    for plan in plan_rows:
        is_active = bool(active_plan_id is not None and plan.id == active_plan_id)
        plan.is_active = 1 if is_active else 0
        if is_active:
            active_plan = plan
    return active_plan
