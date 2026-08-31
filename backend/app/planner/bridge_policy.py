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
    # Interdisciplinary curricula need one structural core bridge plus the
    # secondary-domain foundation/data/project/integration sequence.  A
    # legacy per-project value of 4 silently capped that sequence and the
    # final assembly dropped SECONDARY_INTEGRATION, leaving the second-domain
    # quota short (notably ict-medicine).  Keep explicit zero disabled, but
    # reserve the five-module envelope for interdisciplinary plans.
    program_type = str(constraints.get("program_type") or "").lower()
    if requested > 0 and program_type in {"interdisciplinary", "joint"}:
        # Interdisciplinary plans need the explicit core + secondary
        # sequence; it has a dedicated seven-module envelope.
        return max(requested, 7)
    return max(0, min(requested, int(settings.MAX_BRIDGE_MODULES)))
