"""Build and persist methodist-facing drafts without weakening publication."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.planner_draft import PlannerBuildDraft


def _json_value(value: Any) -> Any:
    """Detach scheduler objects and keep the draft portable JSON."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def build_rejected_draft_payloads(
    variants: dict[str, dict], rejected_variants: list[dict], *, job_id: str | None,
) -> list[dict]:
    """Return durable snapshots for rejected variants only.

    The payload intentionally includes the real candidate schedule and final
    verifier facts, but no mutable ORM row/plan id.  It is therefore safe to
    retain after the failed plan transaction has rolled back.
    """
    payloads: list[dict] = []
    for rejection in rejected_variants:
        variant_type = str(rejection.get("variant") or "").upper()
        result = variants.get(variant_type) or {}
        schedule = result.get("schedule") or {}
        if variant_type not in {"A", "B", "C"} or not isinstance(schedule, dict):
            continue
        metrics = result.get("metrics") or {}
        verification = result.get("verification") or metrics.get("verification") or {}
        payloads.append({
            "job_id": job_id,
            "variant_type": variant_type,
            "schedule_json": _json_value(schedule),
            "metrics_json": _json_value(metrics),
            "rejection_json": _json_value({
                "hard": int(rejection.get("hard") or 0),
                "hard_details": rejection.get("hard_details") or [],
                "quality_violations": rejection.get("quality_violations") or [],
                "verification": verification,
            }),
        })
    return payloads


def persist_rejected_drafts(
    db: Session,
    *,
    project_version_id: int,
    created_by_user_id: int | None,
    payloads: list[dict],
) -> list[PlannerBuildDraft]:
    """Store a new build's drafts.  A repeated worker claim stays idempotent."""
    rows: list[PlannerBuildDraft] = []
    for payload in payloads:
        job_id = payload.get("job_id")
        variant_type = payload["variant_type"]
        existing = None
        if job_id:
            existing = db.query(PlannerBuildDraft).filter(
                PlannerBuildDraft.job_id == job_id,
                PlannerBuildDraft.variant_type == variant_type,
            ).first()
        if existing is not None:
            rows.append(existing)
            continue
        row = PlannerBuildDraft(
            project_version_id=project_version_id,
            created_by_user_id=created_by_user_id,
            job_id=job_id,
            variant_type=variant_type,
            schedule_json=payload["schedule_json"],
            metrics_json=payload["metrics_json"],
            rejection_json=payload["rejection_json"],
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def draft_summary(row: PlannerBuildDraft) -> dict:
    """Small listing DTO; schedule remains available only to the owner route."""
    verification = (row.rejection_json or {}).get("verification") or {}
    return {
        "id": row.id,
        "job_id": row.job_id,
        "variant_type": row.variant_type,
        "created_at": row.created_at,
        "hard_violation_count": int(verification.get("hard_violation_count") or (row.rejection_json or {}).get("hard") or 0),
        "total_credits": verification.get("total_credits"),
        "target_credits": verification.get("target_credits"),
        "semester_loads": verification.get("semester_loads") or {},
        "domain_credits": verification.get("domain_credits") or {},
        "min_lo_coverage": verification.get("min_lo_coverage"),
        "hard_details": (row.rejection_json or {}).get("hard_details") or [],
    }
