"""Small, dependency-free policy helpers for generated bridge modules."""
from __future__ import annotations

from app.config import settings


def bridge_module_limit(project_version) -> int:
    """Return the non-bypassable bridge budget for one programme version."""
    constraints = project_version.project.constraints_json or {}
    if not constraints.get("allow_new_courses", True):
        return 0
    try:
        requested = int(constraints.get("max_new_courses", settings.MAX_BRIDGE_MODULES))
    except (TypeError, ValueError):
        requested = settings.MAX_BRIDGE_MODULES
    return max(0, min(requested, int(settings.MAX_BRIDGE_MODULES)))


def scheduled_bridge_count(schedule: dict) -> int:
    """Count every generated module in a schedule, including the core bridge.

    A structural bridge remains a new curriculum unit.  Excluding it from a
    user-facing limit makes a cap of one mean two different things in the
    planner and verifier.
    """
    return sum(
        1
        for items in schedule.values()
        for item in items or []
        if isinstance(item, dict) and item.get("bridge_module_id") is not None
    )


def bridge_can_close_program_lo(bridge) -> bool:
    """Whether a bridge is approved evidence, rather than a generated proposal.

    A target-LO label is authored by the same planner that is being verified;
    it cannot independently prove that a student has a credible learning path.
    Only a review-approved module with traceable source evidence may contribute
    to this strict gate. The UI may still display generated bridges as
    proposals needing expert review.
    """
    parameters = getattr(bridge, "generation_params_json", None)
    sources = getattr(bridge, "source_chunks_json", None)
    targets = getattr(bridge, "target_los", None)
    return bool(
        isinstance(parameters, dict)
        and parameters.get("evidence_status") == "approved"
        and isinstance(sources, list)
        and sources
        and isinstance(targets, list)
        and targets
    )
