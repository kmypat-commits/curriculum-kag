"""Read-only transactional check of one selector variant using saved scores."""
from __future__ import annotations

import argparse
import json

from app.database import SessionLocal
from app.models.embedding import MatchScore
from app.models.course import Course
from app.models.project import ProjectVersion
from app.planner.scheduler import select_courses_for_variant


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--variant", default="A")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        version = db.query(ProjectVersion).filter(ProjectVersion.id == args.version).first()
        items = select_courses_for_variant(args.version, db, args.variant.upper())
        course_ids = [int(item["course_id"]) for item in items if item.get("course_id")]
        rows = db.query(MatchScore).filter(
            MatchScore.project_version_id == args.version,
            MatchScore.course_id.in_(course_ids or [-1]),
        ).all()
        effective_by_course = {}
        effective_by_lo = {}
        for row in rows:
            expert = float((row.evidence_json or {}).get("epvo_expert_score") or 0.0)
            effective = max(float(row.score or 0.0), expert)
            effective_by_course[row.course_id] = max(effective_by_course.get(row.course_id, 0.0), effective)
            effective_by_lo[row.lo_id] = max(effective_by_lo.get(row.lo_id, 0.0), effective)
        domains = {}
        selected_prerequisite_ids = {
            int(prerequisite_id)
            for item in items
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in course_ids
        }
        course_titles = {
            row.id: row.title
            for row in db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()
        }
        weak_details = [
            {
                "course_id": course_id,
                "title": course_titles.get(course_id),
                "score": round(effective_by_course.get(course_id, 0.0), 4),
                "structural_prerequisite": course_id in selected_prerequisite_ids,
            }
            for course_id in course_ids
            if effective_by_course.get(course_id, 0.0) < 0.4
        ]
        for item in items:
            key = str(item.get("domain") or "bridge")
            domains[key] = domains.get(key, 0) + int(item.get("credits") or 0)
        print(json.dumps({
            "variant": args.variant.upper(),
            "credits": sum(int(item.get("credits") or 0) for item in items),
            "courses": len(items),
            "bridges": sum(1 for item in items if item.get("bridge_module_id")),
            "domain_credits": domains,
            "weak_courses": len(weak_details),
            "weak_details": weak_details,
            "los_without_real_050": sum(1 for lo in version.learning_outcomes if effective_by_lo.get(lo.id, 0.0) < 0.5),
        }, ensure_ascii=False, indent=2))
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
