from typing import Dict, List
from sqlalchemy.orm import Session
from app.models.project import ProjectVersion
from app.models.embedding import MatchScore
from app.config import settings


def detect_gaps(project_version_id: int, db: Session) -> Dict:
    """Detect LOs whose cumulative probabilistic coverage is below threshold."""
    project_version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not project_version:
        raise ValueError(f"Project version {project_version_id} not found")
    gaps: List[Dict] = []
    for lo in project_version.learning_outcomes:
        rows = db.query(MatchScore).filter(MatchScore.project_version_id == project_version_id, MatchScore.lo_id == lo.id).all()
        scores = [max(0.0, min(1.0, row.score)) for row in rows]
        product = 1.0
        for score in scores:
            product *= 1.0 - score
        coverage = 1.0 - product if scores else 0.0
        max_single = max(scores) if scores else 0.0
        if coverage < settings.COVERAGE_THRESHOLD:
            gaps.append({
                "lo_id": lo.id,
                "lo_code": lo.lo_code,
                "lo_text": lo.lo_text,
                "coverage": round(coverage, 3),
                "probabilistic_coverage": round(coverage, 3),
                "max_coverage": round(coverage, 3),
                "max_single_score": round(max_single, 3),
                "num_courses": len(scores),
                "gap_size": round(settings.COVERAGE_THRESHOLD - coverage, 3),
            })
    total_los = len(project_version.learning_outcomes)
    return {"total_los": total_los, "gap_count": len(gaps), "gap_percentage": round(len(gaps) / total_los * 100, 1) if total_los else 0, "threshold": settings.COVERAGE_THRESHOLD, "gaps": gaps}
