"""Recalculate metrics for the latest A/B/C without changing plan items."""

from __future__ import annotations

import argparse
import json

from app.database import SessionLocal
from app.models.bridge_module import BridgeModule
from app.models.course import Course
from app.models.plan import Plan, PlanItem
from app.planner.scheduler import calculate_plan_metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version_id", type=int)
    args = parser.parse_args()
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
            for item in items:
                course = courses.get(item.course_id)
                bridge = bridges.get(item.bridge_module_id)
                schedule.setdefault(int(item.semester), []).append({
                    "course_id": item.course_id,
                    "bridge_module_id": item.bridge_module_id,
                    "title": course.title if course else bridge.title if bridge else "Неизвестная дисциплина",
                    "domain": course.domain if course else "interdisciplinary",
                    "credits": int(item.credits or 0),
                    "type": item.course_type,
                    "prerequisites": list(item.prerequisites_snapshot or []),
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
            }
        db.commit()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
