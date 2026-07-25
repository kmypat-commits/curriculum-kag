"""Adopt already verified planner outputs as the initial persistent stage cache."""
from sqlalchemy import func

from app.database import SessionLocal
from app.models.embedding import MatchScore
from app.models.plan import Plan
from app.models.project import ProjectVersion
from app.services.planner_stage_cache import (
    EPVO_CACHE_ACTION, SCORING_CACHE_ACTION, epvo_input_signature,
    remember_cache, scoring_input_signature,
)


def main() -> None:
    db = SessionLocal()
    seeded = []
    try:
        versions = db.query(ProjectVersion).filter(
            ProjectVersion.id.in_(db.query(Plan.project_version_id).distinct())
        ).all()
        for version in versions:
            lo_ids = [lo.id for lo in version.learning_outcomes]
            matched_los = int(db.query(func.count(func.distinct(MatchScore.lo_id))).filter(
                MatchScore.project_version_id == version.id,
                MatchScore.lo_id.in_(lo_ids or [-1]),
            ).scalar() or 0)
            if not lo_ids or matched_los != len(lo_ids):
                continue
            user_id = version.project.created_by
            remember_cache(db, version, EPVO_CACHE_ACTION, epvo_input_signature(version, db), user_id, {
                "adopted_existing_result": True,
            })
            remember_cache(db, version, SCORING_CACHE_ACTION, scoring_input_signature(version, db), user_id, {
                "adopted_existing_result": True,
                "total_los": len(lo_ids),
                "covered_los": matched_los,
            })
            seeded.append(version.id)
        db.commit()
        print({"seeded_project_versions": seeded, "count": len(seeded)})
    finally:
        db.close()


if __name__ == "__main__":
    main()
