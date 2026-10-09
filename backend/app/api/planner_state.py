from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextvars import ContextVar
import logging
import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.plan_build_status import PlanBuildStatus
from app.models.planner_build_job import PlannerBuildAttempt, PlannerBuildJob
from app.config import settings


DEFAULT_STATUS = {"state": "idle", "stage": "idle", "progress": 0}

# A tiny cache keeps hot polling cheap. PostgreSQL remains the source of truth:
# after an API restart the next read restores the latest persisted snapshot.
plan_build_status: dict[int, dict[str, Any]] = {}
logger = logging.getLogger(__name__)
_build_owner_token: ContextVar[str | None] = ContextVar("planner_build_owner_token", default=None)


def _durable_session(db: Any) -> bool:
    """Keep lightweight state-machine doubles out of persistence history."""
    return isinstance(db, Session)


def _record_job_transition(
    db: Any,
    *,
    project_version_id: int,
    current: dict[str, Any],
    requested_state: str,
    now: datetime,
) -> None:
    """Create/update a job and append a separate attempt for a worker claim."""
    if not _durable_session(db):
        return
    public_id = str(current.get("job_id") or "")
    request_hash = str(current.get("request_hash") or "")
    if not public_id or not request_hash:
        raise RuntimeError("planner build claim is missing durable job identity")
    # A previous API/worker crash can leave the job ledger active while the
    # public status row has already been reconciled to a terminal state.  The
    # partial unique index must not turn that recoverable condition into a
    # permanent 409; close only the orphan for this version before enqueue.
    terminal_states = {"complete", "failed", "cancelled", "timed_out", "rejected", "infeasible"}
    if current.get("state") in terminal_states and requested_state == "queued":
        orphaned = (
            db.query(PlannerBuildJob)
            .filter(
                PlannerBuildJob.project_version_id == project_version_id,
                PlannerBuildJob.state.in_(("queued", "running")),
            )
            .with_for_update()
            .all()
        )
        for old_job in orphaned:
            old_job.state = str(current["state"])
            old_job.finished_at = now
            old_job.cancel_requested = int(current.get("cancel_requested") or 0)
            old_attempts = db.query(PlannerBuildAttempt).filter(
                PlannerBuildAttempt.job_id == old_job.id,
            ).all()
            for old_attempt in old_attempts:
                if old_attempt.state == "running":
                    old_attempt.state = str(current["state"])
                    old_attempt.finished_at = now
                    old_attempt.lease_expires_at = None
    job = (
        db.query(PlannerBuildJob)
        .filter(PlannerBuildJob.public_id == public_id)
        .with_for_update()
        .first()
    )
    if job is None:
        job = PlannerBuildJob(
            public_id=public_id,
            project_version_id=project_version_id,
            requested_by_user_id=current.get("requested_by_user_id"),
            request_hash=request_hash,
            program_spec_json=current.get("program_spec_json"),
            program_spec_hash=current.get("program_spec_hash"),
            idempotency_key=current.get("idempotency_key"),
            state="queued" if requested_state == "queued" else "running",
            queued_at=now,
            deadline_at=now + timedelta(seconds=settings.BUILD_DEADLINE_SECONDS),
        )
        db.add(job)
        db.flush()
    if requested_state != "running":
        return
    # The status-row lock and lease check already admitted this new owner.
    # A same-owner re-entry returns before this function. Close abandoned
    # executions of this logical job, not the recoverable job itself.
    for previous_attempt in db.query(PlannerBuildAttempt).filter(
        PlannerBuildAttempt.job_id == job.id,
        PlannerBuildAttempt.state == "running",
    ).all():
        previous_attempt.state = "timed_out"
        previous_attempt.failure_code = "lease_expired"
        previous_attempt.finished_at = now
        previous_attempt.lease_expires_at = None
    job.state = "running"
    job.started_at = job.started_at or now
    # Heartbeats refresh only an attempt lease, never this absolute deadline.
    job.deadline_at = job.deadline_at or (now + timedelta(seconds=settings.BUILD_DEADLINE_SECONDS))
    next_ordinal = int(
        db.query(PlannerBuildAttempt).filter(PlannerBuildAttempt.job_id == job.id).count()
    ) + 1
    db.add(PlannerBuildAttempt(
        job_id=job.id,
        ordinal=next_ordinal,
        owner_token=str(current["worker_id"]),
        state="running",
        started_at=now,
        heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=settings.BUILD_LEASE_SECONDS),
    ))


def _record_terminal_job_state(db: Any, current: dict[str, Any], state: str, now: datetime) -> None:
    """Mirror a terminal public snapshot into its durable job/attempt rows."""
    if not _durable_session(db):
        return
    public_id = current.get("job_id")
    if not public_id:
        return
    job = db.query(PlannerBuildJob).filter(PlannerBuildJob.public_id == public_id).first()
    if job is None:
        return
    job.state = state
    job.finished_at = now
    job.cancel_requested = int(current.get("cancel_requested") or 0)
    owner_token = current.get("worker_id")
    if not owner_token:
        return
    attempt = (
        db.query(PlannerBuildAttempt)
        .filter(
            PlannerBuildAttempt.job_id == job.id,
            PlannerBuildAttempt.owner_token == owner_token,
            PlannerBuildAttempt.state == "running",
        )
        .first()
    )
    if attempt is not None:
        attempt.state = state
        attempt.finished_at = now
        attempt.lease_expires_at = None
        if state in {"failed", "timed_out", "infeasible"}:
            attempt.failure_code = state


def _serialise(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return result


def set_build_status(project_version_id: int, **payload: Any) -> dict[str, Any]:
    """Merge and persist progress without committing the caller's work session."""
    current = get_build_status(project_version_id)
    expected_owner = _build_owner_token.get()
    if expected_owner and current.get("worker_id") and current.get("worker_id") != expected_owner:
        logger.warning(
            "ignored stale planner build status update",
            extra={"project_version_id": project_version_id},
        )
        return current
    previous_stage = current.get('stage')
    previous_state = current.get('state')
    current.update(payload)
    current = _serialise(current)
    if current.get("state") == "running":
        current["heartbeat_at"] = current["updated_at"]
        current["lease_expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=settings.BUILD_LEASE_SECONDS)
        ).isoformat()
        current.pop("stale", None)
    else:
        # A recovered retry or a terminal result must not inherit stale lease
        # markers from the previous attempt into the public status payload.
        current.pop("stale", None)
        current.pop("heartbeat_at", None)
        current.pop("lease_expires_at", None)
    plan_build_status[project_version_id] = current
    try:
        with SessionLocal.begin() as db:
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
            row.job_id = current.get("job_id")
            row.request_hash = current.get("request_hash")
            row.worker_id = current.get("worker_id")
            row.heartbeat_at = datetime.now(timezone.utc) if row.state == "running" else None
            row.lease_expires_at = datetime.fromisoformat(current["lease_expires_at"]) if current.get("lease_expires_at") else None
            row.cancel_requested = int(current.get("cancel_requested") or 0)
            row.idempotency_key = current.get("idempotency_key")
            if (settings.BUILD_TELEMETRY_ENABLED and row.job_id
                    and (previous_stage != row.stage or previous_state != row.state)):
                from app.services.build_events import append_event
                db.flush()
                append_event(db, project_version_id, row.job_id, 'stage', {
                    'stage': row.stage, 'state': row.state, 'progress': row.progress,
                    'elapsed_seconds': current.get('elapsed_seconds'),
                    'error': current.get('error'),
                    'publication_status': current.get('publication_status'),
                    'published_variants': current.get('published_variants'),
                }, worker_id=expected_owner)
            if row.state in {"complete", "failed", "cancelled", "timed_out", "rejected", "infeasible"}:
                _record_terminal_job_state(db, current, row.state, datetime.now(timezone.utc))
            db.commit()
    except SQLAlchemyError:
        # Do not convert a recoverable status-write problem into a failed build.
        # The in-memory snapshot still serves the currently running process.
        pass
    return current


def touch_build_lease(project_version_id: int, worker_id: str | None = None) -> bool:
    """Extend a live lease independently from stage/progress callbacks.

    Long scoring or planner stages may not emit progress for several seconds.
    A dedicated heartbeat must therefore update the durable row atomically and
    must never resurrect a terminal job or a different worker's attempt.
    """
    now = datetime.now(timezone.utc)
    try:
        with SessionLocal.begin() as db:
            row = db.query(PlanBuildStatus).filter(
                PlanBuildStatus.project_version_id == project_version_id,
            ).with_for_update().first()
            if row is None or row.state != "running":
                return False
            if worker_id and row.worker_id and row.worker_id != worker_id:
                return False
            payload = dict(row.payload_json) if isinstance(row.payload_json, dict) else {}
            payload["updated_at"] = now.isoformat()
            payload["heartbeat_at"] = now.isoformat()
            payload["lease_expires_at"] = (
                now + timedelta(seconds=settings.BUILD_LEASE_SECONDS)
            ).isoformat()
            row.payload_json = payload
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=settings.BUILD_LEASE_SECONDS)
            plan_build_status[project_version_id] = payload
            return True
    except SQLAlchemyError:
        return False


def replace_build_status(project_version_id: int, **payload: Any) -> dict[str, Any]:
    plan_build_status.pop(project_version_id, None)
    return set_build_status(project_version_id, **payload)


def request_build_cancel(project_version_id: int) -> dict[str, Any]:
    """Persist a cancellation request; the running build observes it at stage boundaries."""
    # Cancellation is a control-plane update, not a heartbeat.  Calling
    # set_build_status() here would extend a dead worker's lease and delay
    # stale recovery every time an operator pressed Cancel.
    current = get_build_status(project_version_id)
    if current.get("state") not in {"queued", "running"}:
        return current
    current = dict(current)
    queued = current.get("state") == "queued"
    current["cancel_requested"] = 1
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    if queued:
        current.update({"state": "cancelled", "stage": "cancelled", "progress": 0})
        current.pop("heartbeat_at", None)
        current.pop("lease_expires_at", None)
    plan_build_status[project_version_id] = current
    try:
        with SessionLocal.begin() as db:
            row = db.query(PlanBuildStatus).filter(
                PlanBuildStatus.project_version_id == project_version_id,
            ).with_for_update().first()
            if row and row.state in {"queued", "running"}:
                payload = dict(row.payload_json) if isinstance(row.payload_json, dict) else {}
                payload.update(current)
                row.payload_json = payload
                row.cancel_requested = 1
                if queued and row.state == "queued":
                    row.state = "cancelled"
                    row.stage = "cancelled"
                    row.progress = 0
                    row.heartbeat_at = None
                    row.lease_expires_at = None
                    _record_terminal_job_state(db, payload, "cancelled", datetime.now(timezone.utc))
                current = payload
                plan_build_status[project_version_id] = current
            elif row:
                # The worker may have completed after the initial read but
                # before this row lock. Never publish a stale running cache.
                current = dict(row.payload_json) if isinstance(row.payload_json, dict) else {
                    "state": row.state,
                    "stage": row.stage,
                    "progress": row.progress,
                }
                plan_build_status[project_version_id] = current
    except SQLAlchemyError:
        # Preserve the in-process request if the durable status store is
        # temporarily unavailable; the next worker boundary will re-check it.
        pass
    return current


def cancellation_requested(project_version_id: int) -> bool:
    return bool(get_build_status(project_version_id).get("cancel_requested"))


def _lease_expired(value: Any, now: datetime | None = None) -> bool:
    if not value:
        return False
    try:
        expiry = datetime.fromisoformat(str(value)) if isinstance(value, str) else value
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry <= (now or datetime.now(timezone.utc))
    except (TypeError, ValueError):
        return False


def _reconcile_stale_snapshot(project_version_id: int, status: dict[str, Any]) -> dict[str, Any]:
    """Expose and persist an expired queued/running lease as a terminal timeout."""
    if status.get("state") not in {"queued", "running"} or not _lease_expired(status.get("lease_expires_at")):
        return status
    status = dict(status)
    status.update({
        "state": "timed_out",
        "stage": "timed_out",
        "stale": True,
        "error": "Построение превысило lease и доступно для повторного запуска",
    })
    plan_build_status[project_version_id] = status
    try:
        with SessionLocal.begin() as db:
            row = db.query(PlanBuildStatus).filter(
                PlanBuildStatus.project_version_id == project_version_id,
            ).first()
            # A worker may die before queued -> running promotion.  That
            # state is just as terminal when its durable lease expires; only
            # reconciling ``running`` leaves an orphaned queue entry that can
            # block every later build for the version.
            if row and row.state in {"queued", "running"} and _lease_expired(row.lease_expires_at):
                row.state = "timed_out"
                row.stage = "timed_out"
                row.payload_json = status
                row.heartbeat_at = None
                row.lease_expires_at = None
                public_id = status.get("job_id")
                if public_id:
                    job = db.query(PlannerBuildJob).filter(
                        PlannerBuildJob.public_id == public_id,
                    ).first()
                    if job is not None and job.state in {"queued", "running"}:
                        job.state = "timed_out"
                        job.finished_at = datetime.now(timezone.utc)
                    if job is not None:
                        for attempt in db.query(PlannerBuildAttempt).filter(
                            PlannerBuildAttempt.job_id == job.id,
                            PlannerBuildAttempt.state == "running",
                        ).all():
                            attempt.state = "timed_out"
                            attempt.finished_at = datetime.now(timezone.utc)
                            attempt.lease_expires_at = None
    except SQLAlchemyError:
        # The snapshot remains truthful for this process; claim_build_status
        # will retry reconciliation when the status store is available.
        pass
    return status


def claim_build_status(project_version_id: int, **payload: Any) -> dict[str, Any] | None:
    """Atomically mark a version as running, or return ``None`` if it is busy.

    PostgreSQL row locking prevents two API workers from starting the same
    expensive build. A durable-store error never grants ownership from the
    process-local cache; the caller must retry after the status store recovers.
    """
    try:
        expected_job_id = payload.pop("_expected_job_id", None)
        with SessionLocal.begin() as db:
            row = (
                db.query(PlanBuildStatus)
                .filter(PlanBuildStatus.project_version_id == project_version_id)
                .with_for_update()
                .first()
            )
            now = datetime.now(timezone.utc)
            requested_state = str(payload.get("state") or "running")
            lease_expiry = row.lease_expires_at if row else None
            if lease_expiry is not None and lease_expiry.tzinfo is None:
                lease_expiry = lease_expiry.replace(tzinfo=timezone.utc)
            lease_expired = bool(lease_expiry and lease_expiry <= now)
            # Cancellation is terminal control-plane state.  An expired
            # lease must never turn a cancelled job back into a runnable one
            # after a worker restart.
            if row is not None and int(row.cancel_requested or 0) == 1 and requested_state == "running":
                return None
            if row is not None and not lease_expired:
                # Only the worker may promote an already queued row to
                # running.  A second API enqueue must not spawn another
                # expensive worker for the same version.
                if row.state == "queued" and requested_state != "running":
                    return None
                if row.state == "running":
                    current_payload = dict(row.payload_json) if isinstance(row.payload_json, dict) else {}
                    same_worker_reentry = (
                        expected_job_id
                        and current_payload.get("job_id") == expected_job_id
                        and current_payload.get("worker_id") == _build_owner_token.get()
                    )
                    # The persistent daemon claims the queued row before
                    # entering build_plan().  That same execution then
                    # re-enters this function; accept only that exact owner
                    # and job, never a second process.
                    if same_worker_reentry:
                        plan_build_status[project_version_id] = current_payload
                        return current_payload
                    return None
            current = dict(row.payload_json) if row and isinstance(row.payload_json, dict) else dict(DEFAULT_STATUS)
            # Existing rows created before the payload contract used columns
            # only.  Restore the durable identity before merging a worker
            # promotion, otherwise queued -> running would accidentally
            # assign a second logical job.
            if row is not None:
                if getattr(row, "job_id", None):
                    current.setdefault("job_id", row.job_id)
                if getattr(row, "request_hash", None):
                    current.setdefault("request_hash", row.request_hash)
                # Preserve the durable terminal decision while preparing a
                # fresh queue request.  The incoming ``state=queued`` must
                # not hide an orphan active ledger row from reconciliation.
                if requested_state == "queued" and row.state in {
                    "complete", "failed", "cancelled", "timed_out", "rejected", "infeasible",
                }:
                    orphaned = (
                        db.query(PlannerBuildJob)
                        .filter(
                            PlannerBuildJob.project_version_id == project_version_id,
                            PlannerBuildJob.state.in_(("queued", "running")),
                        )
                        .with_for_update()
                        .all()
                    )
                    for old_job in orphaned:
                        old_job.state = row.state
                        old_job.finished_at = now
                        old_job.cancel_requested = int(row.cancel_requested or 0)
                        old_attempts = db.query(PlannerBuildAttempt).filter(
                            PlannerBuildAttempt.job_id == old_job.id,
                        ).all()
                        for old_attempt in old_attempts:
                            if old_attempt.state == "running":
                                old_attempt.state = row.state
                                old_attempt.finished_at = now
                                old_attempt.lease_expires_at = None
            # A detached worker belongs to the exact job the API enqueued.
            # It must never promote a newer job after an old queued process
            # wakes up following cancel/retry.
            if expected_job_id and current.get("job_id") != expected_job_id:
                return None
            if expected_job_id and current.get("state") in {
                "complete", "failed", "cancelled", "timed_out", "rejected", "infeasible",
            }:
                return None
            # Durable identity recovered from columns must not be erased by
            # an older worker payload that omitted the field (represented as
            # ``None``).  Losing the request hash here makes the subsequent
            # job-history write fail and leaves the queued row untouched.
            for identity_key in ("job_id", "request_hash"):
                if payload.get(identity_key) is None and current.get(identity_key) is not None:
                    payload[identity_key] = current[identity_key]
            current.update(payload)
            if requested_state == "queued":
                # A retry is a new logical job; cancellation belongs only to
                # the previous job and must not poison the fresh queue row.
                current["cancel_requested"] = 0
            # A fresh execution must not present the terminal message from a
            # previous cancellation/failure while it is running.  Keep the
            # current state self-contained and let the new execution write a
            # terminal error only if one actually occurs.
            current.pop("error", None)
            current.pop("verification_summary", None)
            current.pop("stale", None)
            # A retry or queued→running promotion is a new owner.  Reusing a
            # prior worker id allows a late process to look authoritative.
            current["worker_id"] = f"planner-{uuid.uuid4().hex[:12]}"
            current["cancel_requested"] = 0
            # Enqueue is not an execution attempt. Count only a worker claim
            # so telemetry does not describe one logical build as two retries.
            prior_attempts = int((getattr(row, "attempt_count", 0) if row else 0) or 0)
            current["attempt_count"] = prior_attempts + (1 if requested_state == "running" else 0)
            if lease_expired:
                current["recovered_stale"] = True
            current = _serialise(current)
            current["heartbeat_at"] = now.isoformat()
            current["lease_expires_at"] = (
                now + timedelta(seconds=settings.BUILD_LEASE_SECONDS)
            ).isoformat()
            # A retry/recovered claim is a new logical execution window.  Do
            # not inherit an expired deadline from the previous attempt;
            # doing so makes the next request fail immediately with 504.
            current["deadline_at"] = (
                now + timedelta(seconds=settings.BUILD_DEADLINE_SECONDS)
            ).isoformat()
            if row is None:
                row = PlanBuildStatus(project_version_id=project_version_id)
                db.add(row)
            row.state = str(current.get("state") or "running")
            row.stage = str(current.get("stage") or "matching")
            row.progress = int(current.get("progress") or 0)
            row.payload_json = current
            row.job_id = current.get("job_id")
            row.request_hash = current.get("request_hash")
            row.worker_id = current["worker_id"]
            row.heartbeat_at = now
            row.lease_expires_at = datetime.fromisoformat(current["lease_expires_at"])
            row.attempt_count = current["attempt_count"]
            row.cancel_requested = 0
            row.idempotency_key = current.get("idempotency_key")
            _record_job_transition(
                db,
                project_version_id=project_version_id,
                current=current,
                requested_state=requested_state,
                now=now,
            )
        plan_build_status[project_version_id] = current
        _build_owner_token.set(current["worker_id"])
        return current
    except SQLAlchemyError:
        # Never grant an expensive build ownership from a process-local cache:
        # another API/worker cannot observe that lease and may publish a
        # competing result. The caller receives a controlled busy/unavailable
        # response and can retry after the durable store recovers.
        logger.exception("durable planner build claim failed", extra={"project_version_id": project_version_id})
        return None


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
                return _reconcile_stale_snapshot(project_version_id, status)
    except SQLAlchemyError:
        cached = plan_build_status.get(project_version_id)
        if cached is not None:
            return _reconcile_stale_snapshot(project_version_id, dict(cached))
    return dict(DEFAULT_STATUS)


def running_build_version_ids() -> list[int]:
    try:
        with SessionLocal() as db:
            rows = db.query(PlanBuildStatus).filter(
                PlanBuildStatus.state.in_(("queued", "running"))
            ).all()
            active: list[int] = []
            for row in rows:
                status = dict(row.payload_json) if isinstance(row.payload_json, dict) else {
                    "state": row.state,
                    "stage": row.stage,
                    "progress": row.progress,
                }
                # The durable columns are authoritative.  A worker may have
                # crashed between a column update and payload serialization,
                # so trusting payload_json here can keep an expired lease
                # visible forever.
                status["state"] = row.state
                status["lease_expires_at"] = (
                    row.lease_expires_at.isoformat() if row.lease_expires_at else None
                )
                reconciled = _reconcile_stale_snapshot(int(row.project_version_id), status)
                if reconciled.get("state") == "running":
                    active.append(int(row.project_version_id))
            return active
    except SQLAlchemyError:
        return [
            version_id
            for version_id, status in plan_build_status.items()
            if status.get("state") == "running"
        ]
