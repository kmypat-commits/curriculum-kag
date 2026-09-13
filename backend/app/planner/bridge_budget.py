"""Pure bridge-budget policy used by the schedule assembly pipeline."""

from __future__ import annotations

from typing import Dict, List

from app.models.project import ProjectVersion
from app.planner.bridge_policy import bridge_module_limit


def cap_bridge_items_to_budget(
    selected_courses: List[Dict],
    project_version: ProjectVersion,
    confirmed_bridge_ids: set[int] | None = None,
) -> List[Dict]:
    """Keep bridge units within the auditable programme budget.

    The function is intentionally pure: it does not query or mutate the
    session, and it preserves the input order for retained items.
    """
    limit = bridge_module_limit(project_version)
    bridges = [item for item in selected_courses if item.get("bridge_module_id") is not None]
    if len(bridges) <= limit:
        return selected_courses
    confirmed = confirmed_bridge_ids or set()
    protected = [item for item in bridges if int(item.get("bridge_module_id") or 0) in confirmed]
    if len(protected) >= limit:
        protected.sort(
            key=lambda item: (
                0 if str(item.get("course_id") or "").startswith("SECONDARY_INTEGRATION_") else
                1 if str(item.get("course_id") or "").startswith("SECONDARY_") else 2,
                -int(item.get("credits") or 0),
            )
        )
        keep = protected[:limit]
    else:
        remaining = [item for item in bridges if item not in protected]
        remaining.sort(
            key=lambda item: (
                0 if str(item.get("course_id") or "").startswith("SECONDARY_INTEGRATION_") else
                1 if str(item.get("course_id") or "").startswith("SECONDARY_") else 2,
                -len(item.get("target_los") or item.get("learning_outcomes") or []),
                -float(item.get("admission_score") or item.get("score") or 0.0),
                int(item.get("credits") or 0),
            )
        )
        keep = protected + remaining[: max(0, limit - len(protected))]
    keep_ids = {id(item) for item in keep}
    return [
        item for item in selected_courses
        if item.get("bridge_module_id") is None or id(item) in keep_ids
    ]
