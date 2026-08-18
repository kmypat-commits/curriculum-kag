"""Recalculate metrics for the latest A/B/C plans.

The default is a read-only preview.  Persisting refreshed metrics requires the
explicit ``--apply`` flag so an audit cannot silently alter user plans.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


# The script is invoked from repository runbooks as ``python
# backend/scripts/...`` as well as from ``backend``.  Make the backend package
# importable in both supported forms instead of relying on a caller-specific
# PYTHONPATH.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version_id", type=int)
    parser.add_argument("--apply", action="store_true", help="Persist the refreshed metrics JSON.")
    parser.add_argument(
        "--database-url",
        help="Optional SQLAlchemy URL. Overrides DATABASE_URL before application imports.",
    )
    args = parser.parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    from app.database import SessionLocal
    from app.models.bridge_module import BridgeModule
    from app.models.course import Course
    from app.models.plan import Plan, PlanItem
    from app.planner.scheduler import calculate_plan_metrics

    db = SessionLocal()
    try:
        plans = db.query(Plan).filter(
            Plan.project_version_id == args.version_id,
            Plan.variant_type.in_(["A", "B", "C"]),
        ).order_by(Plan.id.desc()).all()
        latest = {}
        for plan in plans:
            latest.setdefault(plan.variant_type, plan)
        result = {}
        for variant, plan in latest.items():
            items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
            course_ids = {item.course_id for item in items if item.course_id}
            bridge_ids = {item.bridge_module_id for item in items if item.bridge_module_id}
            courses = {row.id: row for row in db.query(Course).filter(Course.id.in_(course_ids or {-1})).all()}
            bridges = {row.id: row for row in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids or {-1})).all()}
            schedule = {}
            constraints = plan.project_version.project.constraints_json or {}
            is_kz_programme = str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() == "KZ"
            for item in items:
                course = courses.get(item.course_id)
                bridge = bridges.get(item.bridge_module_id)
                course_code = str(course.course_id or "") if course else ""
                regulatory_required = bool(
                    is_kz_programme and course_code.startswith("GOSO-KZ-")
                )
                schedule.setdefault(int(item.semester), []).append({
                    "course_id": item.course_id,
                    "bridge_module_id": item.bridge_module_id,
                    "title": course.title if course else bridge.title if bridge else "Неизвестная дисциплина",
                    "domain": course.domain if course else "interdisciplinary",
                    "credits": int(item.credits or 0),
                    "type": item.course_type,
                    "prerequisites": list(item.prerequisites_snapshot or []),
                    # PlanItem intentionally stores a compact immutable
                    # snapshot. Rehydrate validator-only attributes from the
                    # authoritative course catalogue, otherwise a saved ГОСО
                    # course looks like an ordinary elective during replay.
                    "recommended_semester": int(
                        course.recommended_semester if course and course.recommended_semester else item.semester
                    ),
                    "regulatory_required": regulatory_required,
                    "selection_method": "kz_goso_2026" if regulatory_required else "persisted_plan_replay",
                })
            selected = [row for rows in schedule.values() for row in rows]
            metrics = calculate_plan_metrics(schedule, selected, plan.project_version, db)
            plan.metrics_json = metrics
            verification = metrics.get("verification") or {}
            result[variant] = {
                "plan_id": plan.id,
                "hard_violations": verification.get("hard_violation_count"),
                "domain_credits": verification.get("domain_credits"),
                "quality_passed": verification.get("quality_passed"),
                "quality_violations": verification.get("quality_violations") or [],
                "goso_violations": (verification.get("goso_compliance") or {}).get("violations") or [],
            }
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps({"applied": args.apply, "variants": result}, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
