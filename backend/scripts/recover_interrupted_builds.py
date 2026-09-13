"""Close build leases when the local launcher intentionally stops services.

Stopping the Windows launcher is an interruption, not a successful worker
completion.  Persisting that fact prevents the next start from being blocked
by a stale ``running`` snapshot while keeping all previously published plans.
"""
from datetime import datetime, timezone
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT.parent / ".env", override=False)

from app.database import SessionLocal  # noqa: E402
from app.models.plan_build_status import PlanBuildStatus  # noqa: E402
from app.models.planner_build_job import PlannerBuildAttempt, PlannerBuildJob  # noqa: E402


def main() -> int:
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
