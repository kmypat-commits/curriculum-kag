from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# Transitional in-process state. Production currently pins one API worker;
# a later migration will persist this structure in PostgreSQL or Redis.
plan_build_status: dict[int, dict[str, Any]] = {}


def set_build_status(project_version_id: int, **payload: Any) -> None:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    plan_build_status.setdefault(project_version_id, {}).update(payload)
