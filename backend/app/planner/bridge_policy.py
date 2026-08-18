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
