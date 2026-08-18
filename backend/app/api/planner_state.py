from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.models.plan_build_status import PlanBuildStatus


DEFAULT_STATUS = {"state": "idle", "stage": "idle", "progress": 0}

# A tiny cache keeps hot polling cheap. PostgreSQL remains the source of truth:
# after an API restart the next read restores the latest persisted snapshot.
plan_build_status: dict[int, dict[str, Any]] = {}


def _serialise(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return result


def set_build_status(project_version_id: int, **payload: Any) -> dict[str, Any]:
    """Merge and persist progress without committing the caller's work session."""
    current = get_build_status(project_version_id)
    current.update(payload)
    current = _serialise(current)
    plan_build_status[project_version_id] = current
    try:
        with SessionLocal() as db:
            row = db.query(PlanBuildStatus).filter(
                PlanBuildStatus.project_version_id == project_version_id
            ).first()
            if row is None:
                row = PlanBuildStatus(project_version_id=project_version_id)
                db.add(row)
            row.state = str(current.get("state") or "idle")
            row.stage = str(current.get("stage") or "idle")
            row.progress = int(current.get("progress") or 0)
            row.payload_json = current
            db.commit()
    except SQLAlchemyError:
        # Do not convert a recoverable status-write problem into a failed build.
        # The in-memory snapshot still serves the currently running process.
        pass
    return current


def replace_build_status(project_version_id: int, **payload: Any) -> dict[str, Any]:
    plan_build_status.pop(project_version_id, None)
    return set_build_status(project_version_id, **payload)


def claim_build_status(project_version_id: int, **payload: Any) -> dict[str, Any] | None:
    """Atomically mark a version as running, or return ``None`` if it is busy.

    PostgreSQL row locking prevents two API workers from starting the same
    expensive build. SQLite and a temporarily unavailable status table retain
    the former in-process fallback so a local recovery is still possible.
    """
    try:
        with SessionLocal.begin() as db:
            row = (
                db.query(PlanBuildStatus)
                .filter(PlanBuildStatus.project_version_id == project_version_id)
                .with_for_update()
                .first()
            )
            if row is not None and row.state == "running":
                return None
            current = dict(row.payload_json) if row and isinstance(row.payload_json, dict) else dict(DEFAULT_STATUS)
            current.update(payload)
            current = _serialise(current)
            if row is None:
                row = PlanBuildStatus(project_version_id=project_version_id)
                db.add(row)
            row.state = str(current.get("state") or "running")
            row.stage = str(current.get("stage") or "matching")
            row.progress = int(current.get("progress") or 0)
            row.payload_json = current
        plan_build_status[project_version_id] = current
        return current
    except SQLAlchemyError:
        current = plan_build_status.get(project_version_id, DEFAULT_STATUS)
        if current.get("state") == "running":
            return None
        return replace_build_status(project_version_id, **payload)


def get_build_status(project_version_id: int) -> dict[str, Any]:
    """Read PostgreSQL first so separate API workers see the same status."""
    try:
        with SessionLocal() as db:
            row = db.query(PlanBuildStatus).filter(
                PlanBuildStatus.project_version_id == project_version_id
            ).first()
            if row and isinstance(row.payload_json, dict):
                status = dict(row.payload_json)
                plan_build_status[project_version_id] = status
                return status
    except SQLAlchemyError:
        cached = plan_build_status.get(project_version_id)
        if cached is not None:
            return dict(cached)
    return dict(DEFAULT_STATUS)


def running_build_version_ids() -> list[int]:
    try:
        with SessionLocal() as db:
            return [
                int(version_id)
                for (version_id,) in db.query(PlanBuildStatus.project_version_id).filter(
                    PlanBuildStatus.state == "running"
                ).all()
            ]
    except SQLAlchemyError:
        return [
            version_id
            for version_id, status in plan_build_status.items()
            if status.get("state") == "running"
        ]
