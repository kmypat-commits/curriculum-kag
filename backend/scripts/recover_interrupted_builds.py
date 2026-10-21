"""Close build leases when the local launcher intentionally stops services.

Stopping the Windows launcher is an interruption, not a successful worker
completion.  Persisting that fact prevents the next start from being blocked
by a stale ``running`` snapshot while keeping all previously published plans.
"""
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if __name__ == "__main__":
    load_dotenv(ROOT.parent / ".env", override=False)

from app.database import SessionLocal  # noqa: E402
from app.models.plan_build_status import PlanBuildStatus  # noqa: E402
from app.models.planner_build_job import PlannerBuildAttempt, PlannerBuildJob  # noqa: E402


def recover_expired_orphans(db, snapshot: Path, *, now=None) -> int:
    """Close expired executions without an active current read-model owner.

    Lock jobs/attempts against heartbeat updates; unknown or live leases are
    preserved. Completed job outcomes remain unchanged when closing their
    abandoned attempts. An exclusive, flushed snapshot precedes any change.
    The caller owns the transaction. Published plans are never touched.
    """
    now = now or datetime.now(timezone.utc)
    candidates = []
    for job in db.query(PlannerBuildJob).filter(PlannerBuildJob.state.in_(
        ("running", "complete", "cancelled", "failed", "rejected", "timed_out"),
    )).with_for_update().all():
        current = db.query(PlanBuildStatus).filter_by(job_id=job.public_id).with_for_update().first()
        if current and current.state in ("queued", "running", "cancellation_requested"):
            continue
        attempts = db.query(PlannerBuildAttempt).filter_by(
            job_id=job.id, state="running",
        ).with_for_update().all()
        if not attempts:
            continue
        def expired(attempt):
            lease = attempt.lease_expires_at
            if lease is None:
                return False
            if lease.tzinfo is None:
                lease = lease.replace(tzinfo=timezone.utc)
            return lease < now
        if all(expired(attempt) for attempt in attempts):
            candidates.append((job, attempts))
    if not candidates:
        return 0
    def serialize(row):
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}
    payload = {
        "reason": "expired_orphan_recovery", "captured_at": now.isoformat(),
        "jobs": [serialize(job) for job, _ in candidates],
        "attempts": [serialize(a) for _, attempts in candidates for a in attempts],
    }
    with Path(snapshot).open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2,
                  default=lambda value: value.isoformat())
        stream.flush()
        os.fsync(stream.fileno())
    for job, attempts in candidates:
        if job.state == "running":
            job.state = "timed_out"
            job.finished_at = now
        for attempt in attempts:
            attempt.state = "timed_out"
            attempt.failure_code = "lease_expired"
            attempt.finished_at = now
            attempt.lease_expires_at = None
    db.flush()
    return len(candidates)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expired-orphans-only", action="store_true")
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    if args.expired_orphans_only:
        if args.snapshot is None:
            parser.error("--snapshot is required for expired orphan recovery")
        with SessionLocal.begin() as db:
            count = recover_expired_orphans(db, args.snapshot)
        print(f"Recovered {count} expired orphaned planner build(s).")
        return 0
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as db:
        rows = (
            db.query(PlanBuildStatus)
            .filter(PlanBuildStatus.state.in_(("queued", "running", "cancellation_requested")))
            .all()
        )
        for row in rows:
            public_id = row.job_id
            row.state = "cancelled"
            row.stage = "launcher_stopped"
            row.progress = 0
            row.worker_id = None
            row.heartbeat_at = None
            row.lease_expires_at = None
            row.cancel_requested = 1
            if not public_id:
                continue
            job = db.query(PlannerBuildJob).filter(PlannerBuildJob.public_id == public_id).first()
            if job and job.state in ("queued", "running", "cancellation_requested"):
                job.state = "cancelled"
                job.finished_at = now
                job.cancel_requested = 1
            if job:
                for attempt in db.query(PlannerBuildAttempt).filter(
                    PlannerBuildAttempt.job_id == job.id,
                    PlannerBuildAttempt.state == "running",
                ).all():
                    attempt.state = "cancelled"
                    attempt.finished_at = now
                    attempt.lease_expires_at = None
        print(f"Recovered {len(rows)} interrupted planner build(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
