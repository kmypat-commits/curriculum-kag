"""Compact read-only diagnostic for EPVO domain quota feasibility."""

from __future__ import annotations

import argparse
import json

from sqlalchemy import String, cast, func

from app.database import SessionLocal
from app.models.course import Course
from app.models.course import course_prerequisites
from app.models.embedding import MatchScore
from app.models.epvo import EpvoDisciplineNormalized
from app.models.plan import Plan, PlanItem
from app.models.project import ProjectVersion


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version_id", type=int)
    parser.add_argument("--run-selector", action="store_true")
    parser.add_argument("--variant", default="A", choices=["A", "B", "C"])
    args = parser.parse_args()
    db = SessionLocal()
    try:
        version = db.get(ProjectVersion, args.version_id)
        if not version:
            raise SystemExit("project version not found")
        constraints = version.project.constraints_json or {}
        groups = [
            str(constraints.get("group_code") or ""),
            str(constraints.get("secondary_group_code") or ""),
        ]
        latest_plan = db.query(Plan).filter(
            Plan.project_version_id == args.version_id,
            Plan.variant_type == "A",
        ).order_by(Plan.id.desc()).first()
        selected_ids = {
            int(row[0]) for row in db.query(PlanItem.course_id).filter(
                PlanItem.plan_id == latest_plan.id,
                PlanItem.course_id.isnot(None),
            ).all()
        } if latest_plan else set()
        prerequisites = {}
        for course_id, prerequisite_id in db.execute(course_prerequisites.select()).fetchall():
            prerequisites.setdefault(int(course_id), set()).add(int(prerequisite_id))
        result = []
        for index, code in enumerate(groups):
            rows = db.query(EpvoDisciplineNormalized.approved_course_id).filter(
                EpvoDisciplineNormalized.approved_course_id.isnot(None),
                cast(EpvoDisciplineNormalized.group_codes, String).like(f'%"{code}"%'),
            ).all() if code else []
            course_ids = {int(row[0]) for row in rows if row[0]}
            scores = {
                int(course_id): float(score or 0)
                for course_id, score in db.query(
                    MatchScore.course_id, func.max(MatchScore.score)
                ).filter(
                    MatchScore.project_version_id == args.version_id,
                    MatchScore.course_id.in_(course_ids or {-1}),
                ).group_by(MatchScore.course_id).all()
            }
            courses = db.query(Course).filter(Course.id.in_(course_ids or {-1})).all()
            relevant = [course for course in courses if scores.get(course.id, 0) >= 0.4]
            strong = [course for course in courses if scores.get(course.id, 0) >= 0.5]
            unselected_relevant = [course for course in relevant if course.id not in selected_ids]
            ready_relevant = [
                course for course in unselected_relevant
                if prerequisites.get(course.id, set()).issubset(selected_ids)
            ]
            result.append({
                "domain_index": index + 1,
                "group_code": code,
                "repository_courses": len(courses),
                "repository_credits": sum(int(course.credits or 0) for course in courses),
                "lo_relevant_courses_0_4": len(relevant),
                "lo_relevant_credits_0_4": sum(int(course.credits or 0) for course in relevant),
                "lo_strong_courses_0_5": len(strong),
                "lo_strong_credits_0_5": sum(int(course.credits or 0) for course in strong),
                "unselected_relevant_courses": len(unselected_relevant),
                "ready_with_current_prerequisites": len(ready_relevant),
                "ready_credits": sum(int(course.credits or 0) for course in ready_relevant),
                "ready_credit_histogram": {
                    str(credits): sum(1 for course in ready_relevant if int(course.credits or 0) == credits)
                    for credits in sorted({int(course.credits or 0) for course in ready_relevant})
                },
                "ready_examples": [
                    {
                        "id": course.id,
                        "title": course.title,
                        "credits": int(course.credits or 0),
                        "score": round(scores.get(course.id, 0), 4),
                    }
                    for course in sorted(ready_relevant, key=lambda row: scores.get(row.id, 0), reverse=True)[:20]
                ],
            })
        if args.run_selector:
            from app.planner.scheduler import select_courses_for_variant

            selected = select_courses_for_variant(args.version_id, db, args.variant)
            domains = [
                str(version.project.domain1 or "").casefold().strip(),
                str(version.project.domain2 or "").casefold().strip(),
            ]
            selected_credits = [0, 0]
            selected_course_ids = {
                int(item["course_id"]) for item in selected if item.get("course_id") is not None
            }
            for item in selected:
                item_domain = str(item.get("domain") or "").casefold().strip()
                for index, domain in enumerate(domains):
                    if domain and (domain in item_domain or item_domain in domain):
                        selected_credits[index] += int(item.get("credits") or 0)
                        break
            lo_max = {
                int(lo_id): float(score or 0)
                for lo_id, score in db.query(
                    MatchScore.lo_id, func.max(MatchScore.score)
                ).filter(
                    MatchScore.project_version_id == args.version_id,
                    MatchScore.course_id.in_(selected_course_ids or {-1}),
                ).group_by(MatchScore.lo_id).all()
            }
            lo_gaps = [
                lo.lo_code for lo in version.learning_outcomes
                if lo_max.get(lo.id, 0) < 0.5
            ]
            result.append({
                "selector_variant": args.variant,
                "items": len(selected),
                "total_credits": sum(int(item.get("credits") or 0) for item in selected),
                "domain_credits_from_items": selected_credits,
                "bridges": sum(1 for item in selected if item.get("bridge_module_id") is not None),
                "real_lo_count_0_5": len(version.learning_outcomes) - len(lo_gaps),
                "real_lo_gaps": lo_gaps,
            })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
