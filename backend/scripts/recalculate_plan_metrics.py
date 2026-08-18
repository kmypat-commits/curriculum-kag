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

from sqlalchemy.exc import SQLAlchemyError


# The script is invoked from repository runbooks as ``python
# backend/scripts/...`` as well as from ``backend``.  Make the backend package
# importable in both supported forms instead of relying on a caller-specific
# PYTHONPATH.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "version_id",
        type=int,
        nargs="?",
        help="Project version to recalculate (omit when using --all).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Recalculate every project version that has A/B/C plans in one transaction.",
    )
    parser.add_argument("--apply", action="store_true", help="Persist the refreshed metrics JSON.")
    parser.add_argument(
        "--database-url",
        help="Optional SQLAlchemy URL. Overrides DATABASE_URL before application imports.",
    )
    args = parser.parse_args()
    if bool(args.version_id) == bool(args.all):
        parser.error("укажите version_id или --all")
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    from app.database import SessionLocal
    from app.models.bridge_module import BridgeModule
    from app.models.course import Course
    from app.models.plan import Plan, PlanItem
    from app.planner.scheduler import calculate_plan_metrics

    db = SessionLocal()
    try:
        version_query = db.query(Plan.project_version_id).filter(
            Plan.variant_type.in_(["A", "B", "C"]),
        )
        if args.version_id is not None:
            version_query = version_query.filter(Plan.project_version_id == args.version_id)
        version_ids = [int(row[0]) for row in version_query.distinct().order_by(Plan.project_version_id).all()]
        if not version_ids:
            raise ValueError("Не найдено версий с планами A/B/C")
        latest = {}
        result = {}
        for version_id in version_ids:
            plans = db.query(Plan).filter(
                Plan.project_version_id == version_id,
                Plan.variant_type.in_(["A", "B", "C"]),
            ).order_by(Plan.id.desc()).all()
            latest.clear()
            for plan in plans:
                latest.setdefault(plan.variant_type, plan)
            version_result = {}
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
                        "recommended_semester": int(
                            course.recommended_semester if course and course.recommended_semester else item.semester
                        ),
                        "regulatory_required": regulatory_required,
                        "selection_method": "kz_goso_2026" if regulatory_required else "persisted_plan_replay",
                    })
                selected = [row for rows in schedule.values() for row in rows]
                metrics = calculate_plan_metrics(schedule, selected, plan.project_version, db)
                if args.apply:
                    plan.metrics_json = metrics
                verification = metrics.get("verification") or {}
                version_result[variant] = {
                    "plan_id": plan.id,
                    "metrics_schema_version": metrics.get("metrics_schema_version"),
                    "hard_violations": verification.get("hard_violation_count"),
                    "domain_credits": verification.get("domain_credits"),
                    "quality_passed": verification.get("quality_passed"),
                    "quality_violations": verification.get("quality_violations") or [],
                    "goso_violations": (verification.get("goso_compliance") or {}).get("violations") or [],
                }
            result[str(version_id)] = version_result
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps({"applied": args.apply, "variants": result}, ensure_ascii=False, indent=2))
        return 0
    except (SQLAlchemyError, OSError, RuntimeError, ValueError):
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
