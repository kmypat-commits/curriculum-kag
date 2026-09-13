"""Report or purge expired planner telemetry without touching security audit events."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

from sqlalchemy import func

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from app.database import SessionLocal
from app.models.audit import AuditEvent


TELEMETRY_ACTION = "planner_build_telemetry"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retention-days", type=int, default=settings.AUDIT_TELEMETRY_RETENTION_DAYS)
    parser.add_argument("--apply", action="store_true", help="Delete expired telemetry; omit for dry-run")
    args = parser.parse_args()
    if args.retention_days <= 0:
        parser.error("--retention-days must be positive")

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.retention_days)
    db = SessionLocal()
    try:
        query = db.query(AuditEvent).filter(
            AuditEvent.action == TELEMETRY_ACTION,
            AuditEvent.timestamp < cutoff,
        )
        count = int(query.with_entities(func.count(AuditEvent.id)).scalar() or 0)
        if args.apply and count:
            query.delete(synchronize_session=False)
            db.commit()
        elif args.apply:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    mode = "deleted" if args.apply else "would delete"
    print(f"planner telemetry: {mode} {count} events older than {args.retention_days} days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
