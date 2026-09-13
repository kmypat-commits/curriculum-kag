"""Run one planner build outside the API worker process.

The API starts this short-lived process only when ASYNC_BUILDS=true.  The
worker reuses the normal build function, so status, leases, cancellation,
telemetry and transactional plan replacement have one implementation.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

from pathlib import Path
from sqlalchemy import and_, or_


BACKEND_ROOT = Path(__file__).resolve().parents[1]
HEARTBEAT_FILE = BACKEND_ROOT.parent / ".runtime" / "planner-worker.heartbeat"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.planner_build import build_plan
from app.database import SessionLocal
from app.models.user import User
from app.models.plan_build_status import PlanBuildStatus
from app.api.planner_state import claim_build_status, get_build_status, set_build_status
from app.schemas.planner import PlannerBuildRequest


logger = logging.getLogger("planner-worker")
_shutdown = False


def _request_shutdown(signum, _frame) -> None:
    global _shutdown
    _shutdown = True
    logger.info("shutdown requested", extra={"signal": signum})


def _normalise_requested_variants(value):
    """Preserve the public default: a normal build produces variant A."""
    return "A" if value is None else value


def _build_one(*, version_id: int, user_id: int, variants, job_id: str, idempotency_key: str | None) -> int:
    db = SessionLocal()
    try:
        os.environ["CURRICULUM_KAG_EXPECTED_JOB_ID"] = job_id
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise RuntimeError("Build owner no longer exists")
        build_plan(
            project_version_id=version_id,
            payload=PlannerBuildRequest(variants=variants),
            db=db,
            current_user=user,
            idempotency_key=idempotency_key,
        )
        return 0
    except Exception:
        logger.exception("planner build failed", extra={"job_id": job_id, "version_id": version_id})
        return 1
    finally:
        db.close()


def _run_daemon(poll_seconds: float, max_jobs: int) -> int:
    """Run a bounded PostgreSQL-backed queue consumer until shutdown.

    The worker claims one job at a time by default.  A queued row is never
    acknowledged before the durable running claim succeeds, so a process
    restart leaves it recoverable through lease reconciliation.
    """
    global _shutdown
    # The daemon is the authoritative executor for durable jobs.  Mark its
    # process explicitly so ``build_plan`` runs the claimed job instead of
    # enqueueing it again when ASYNC_BUILDS is enabled.
    os.environ["CURRICULUM_KAG_WORKER"] = "1"
    signal.signal(signal.SIGINT, _request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_shutdown)
    logger.info("planner worker started", extra={"max_jobs": max_jobs})
    while not _shutdown:
        # A PID alone is insufficient on Windows: a wedged Python process can
        # remain alive while no longer polling the durable queue.  The
        # launcher uses this heartbeat to distinguish a live worker from a
        # stale PID.
        try:
            HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
            HEARTBEAT_FILE.touch()
        except OSError:
            logger.warning("worker heartbeat write failed", exc_info=True)
        claimed = False
        db = SessionLocal()
        try:
            rows = (
                db.query(PlanBuildStatus)
                .filter(
                    or_(
                        and_(
                            PlanBuildStatus.state == "queued",
                            PlanBuildStatus.cancel_requested == 0,
                        ),
                        and_(
                            PlanBuildStatus.state.in_(("queued", "running")),
                            PlanBuildStatus.cancel_requested == 1,
                        ),
                        and_(
                            PlanBuildStatus.state == "running",
                            PlanBuildStatus.cancel_requested == 0,
                            PlanBuildStatus.lease_expires_at.is_not(None),
                            PlanBuildStatus.lease_expires_at <= datetime.now(timezone.utc),
                        ),
                    )
                )
                .order_by(PlanBuildStatus.updated_at, PlanBuildStatus.id)
                # PostgreSQL workers must not select the same queued rows
                # before the durable claim.  The state claim remains the
                # authority (and protects against stale snapshots), while
                # SKIP LOCKED prevents needless duplicate work under normal
                # concurrent polling.  SQLite simply ignores this clause.
                .with_for_update(skip_locked=True)
                .limit(max_jobs)
                .all()
            )
            # ``claim_build_status`` deliberately opens its own transaction
            # so that the claim and job-history writes are atomic.  Release
            # the selection lock before calling it; otherwise this polling
            # session would wait forever on the same row it locked above.
            db.commit()
            logger.debug("queue poll returned %d queued row(s)", len(rows))
            for row in rows:
                status = dict(row.payload_json or {})
                job_id = str(status.get("job_id") or row.job_id or "")
                if int(row.cancel_requested or 0) == 1:
                    set_build_status(
                        int(row.project_version_id),
                        state="cancelled",
                        stage="cancelled",
                        progress=0,
                        error="Построение отменено пользователем.",
                    )
                    claimed = True
                    continue
                # A null requested_variants is the public API's normal
                # shorthand for all A/B/C variants.  Normalize it before
                # recoverability checks so a valid queued job is not left
                # spinning forever as "not recoverable".
                variants = _normalise_requested_variants(status.get("requested_variants"))
                # The durable row is authoritative for ownership. Older
                # queued snapshots may not contain this field in payload_json.
                user_id = status.get("requested_by_user_id") or getattr(row, "requested_by_user_id", None)
                logger.debug(
                    "queue row id=%s version_id=%s job_id=%s recoverable=%s",
                    row.id, row.project_version_id, job_id, bool(job_id and user_id and variants is not None),
                )
                if not job_id or not user_id or variants is None:
                    logger.error("queued job is not recoverable", extra={"version_id": row.project_version_id, "job_id": job_id})
                    continue
                running = claim_build_status(
                    int(row.project_version_id),
                    _expected_job_id=job_id,
                    job_id=job_id,
                    request_hash=status.get("request_hash"),
                    program_spec_json=status.get("program_spec_json"),
                    program_spec_hash=status.get("program_spec_hash"),
                    requested_by_user_id=int(user_id),
                    state="running", stage="matching", progress=5,
                    idempotency_key=status.get("idempotency_key"),
                )
                logger.debug("durable claim result job_id=%s claimed=%s", job_id, running is not None)
                if running is None:
                    continue
                claimed = True
                result = _build_one(
                    version_id=int(row.project_version_id),
                    user_id=int(user_id),
                    variants=variants,
                    job_id=job_id,
                    idempotency_key=status.get("idempotency_key"),
                )
                if result != 0:
                    # A worker-side exception can occur after claim but before
                    # build_plan persists its terminal state. Do not leave a
                    # durable job looking alive until lease expiry.
                    current = get_build_status(int(row.project_version_id))
                    if current.get("state") == "running" and current.get("job_id") == job_id:
                        set_build_status(
                            int(row.project_version_id),
                            state="failed",
                            stage="infrastructure_failed",
                            progress=0,
                            error="Planner worker завершился с ошибкой; повторите построение.",
                        )
                break
        except Exception:
            logger.exception("queue poll failed")
        finally:
            db.close()
        if not claimed:
            time.sleep(max(0.5, poll_seconds))
    logger.info("planner worker stopped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--max-jobs", type=int, default=1)
    parser.add_argument("--version-id", type=int)
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--variants")
    parser.add_argument("--job-id")
    parser.add_argument("--idempotency-key")
    args = parser.parse_args()
    if args.daemon:
        logging.basicConfig(level=os.environ.get("PLANNER_WORKER_LOG_LEVEL", "INFO"))
        return _run_daemon(args.poll_seconds, max(1, args.max_jobs))
    if args.version_id is None or args.user_id is None or args.variants is None or args.job_id is None:
        parser.error("one-shot mode requires --version-id, --user-id, --variants and --job-id")
    try:
        variants = json.loads(args.variants)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid variants payload: {exc}")

    return _build_one(
        version_id=args.version_id,
        user_id=args.user_id,
        variants=variants,
        job_id=args.job_id,
        idempotency_key=args.idempotency_key,
    )


if __name__ == "__main__":
    raise SystemExit(main())
