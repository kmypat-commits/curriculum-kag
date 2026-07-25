"""Compact diagnostics for the audited suspicious-course replacement pool."""
import argparse
import json

from sqlalchemy import func

from app.database import SessionLocal
from app.models.course import Course
from app.models.embedding import MatchScore
from app.models.plan import Plan, PlanItem


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--variant", default="A")
    parser.add_argument("--course", type=int, required=True)
    args = parser.parse_args()
    db = SessionLocal()
    try:
        plan = db.query(Plan).filter(
            Plan.project_version_id == args.version,
            Plan.variant_type == args.variant.upper(),
        ).order_by(Plan.is_active.desc(), Plan.id.desc()).first()
        item = db.query(PlanItem).filter(PlanItem.plan_id == plan.id, PlanItem.course_id == args.course).first()
        targets = db.query(MatchScore).filter(
            MatchScore.project_version_id == args.version,
            MatchScore.course_id == args.course,
        ).order_by(MatchScore.score.desc()).limit(4).all()
        target_ids = [row.lo_id for row in targets]
        used = {row[0] for row in db.query(PlanItem.course_id).filter(PlanItem.plan_id == plan.id).all() if row[0]}
        matches = db.query(MatchScore).filter(
            MatchScore.project_version_id == args.version,
            MatchScore.lo_id.in_(target_ids),
            MatchScore.course_id.notin_(used),
        ).all()
        by_course = {}
        for match in matches:
            evidence = match.evidence_json or {}
            value = max(float(match.score or 0), float(evidence.get("epvo_expert_score") or 0))
            by_course.setdefault(match.course_id, {})[match.lo_id] = value
        courses = db.query(Course).filter(
            Course.id.in_(list(by_course) or [-1]), Course.credits == int(item.credits)
        ).all()
        rows = [{
            "id": course.id,
            "title": course.title,
            "domain": course.domain,
            "semester": course.recommended_semester,
            "scores": by_course[course.id],
            "covered": sum(value >= 0.4 for value in by_course[course.id].values()),
            "mean": round(sum(by_course[course.id].values()) / max(1, len(target_ids)), 4),
        } for course in courses]
        rows.sort(key=lambda row: (row["covered"], row["mean"]), reverse=True)
        print(json.dumps({"target_lo_ids": target_ids, "candidates": rows[:30]}, ensure_ascii=True))
    finally:
        db.close()


if __name__ == "__main__":
    main()
