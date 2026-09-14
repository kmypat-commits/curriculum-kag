"""Frozen, compact evidence for a published plan's selected disciplines."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.models.embedding import MatchScore
from app.models.project import LearningOutcome
from app.planner.match_aggregation import semantic_evidence_score


SELECTION_EVIDENCE_SNAPSHOT_VERSION = 2


def snapshot_payload(
    rows: list[Any],
    lo_by_id: dict[int, Any],
    selection_methods: dict[int, str] | None = None,
) -> dict[str, dict]:
    """Make stable, small course-to-LO evidence from rows read at publish time.

    Ranking scores may be recomputed after a plan is published.  This payload
    deliberately stores only the signals used to explain the original choice,
    rather than a mutable ORM object or a full score matrix.
    """
    by_course: dict[int, list[Any]] = defaultdict(list)
    for row in rows:
        if row.course_id is not None and row.lo_id in lo_by_id:
            by_course[int(row.course_id)].append(row)

    result: dict[str, dict] = {}
    for course_id, course_rows in by_course.items():
        def evidence_value(row: Any) -> float:
            return max(
                semantic_evidence_score(row),
                float((row.evidence_json or {}).get("epvo_expert_score") or 0),
            )

        ordered = sorted(course_rows, key=evidence_value, reverse=True)
        top_matches = []
        for row in ordered[:3]:
            lo = lo_by_id[row.lo_id]
            evidence = row.evidence_json or {}
            ai_score = round(float(semantic_evidence_score(row)), 4)
            expert_score = round(float(evidence.get("epvo_expert_score") or 0), 4)
            effective_score = round(max(ai_score, expert_score), 4)
            top_matches.append({
                "lo_id": int(lo.id),
                "lo_code": lo.lo_code,
                "lo_text": lo.lo_text,
                "score": effective_score,
                "effective_score": effective_score,
                "ai_score": ai_score,
                "expert_score": expert_score,
                "source": evidence.get("source") or evidence.get("label") or row.model_name,
                "snapshot": True,
            })
        result[str(course_id)] = {
            "max_score": round(max((evidence_value(row) for row in course_rows), default=0.0), 4),
            "expert_supported": any(
                float((row.evidence_json or {}).get("epvo_expert_score") or 0) > 0
                for row in course_rows
            ),
            "top_lo_matches": top_matches,
        }
    # Some valid selected disciplines (for example, a practice or a real
    # credit top-up) have no direct MatchScore row. Preserve their immutable
    # selection basis too, rather than making a later UI/PDF guess from the
    # mutable catalogue.
    for course_id, selection_method in (selection_methods or {}).items():
        evidence = result.setdefault(str(course_id), {
            "max_score": 0.0,
            "expert_supported": False,
            "top_lo_matches": [],
        })
        if selection_method:
            evidence["selection_method"] = str(selection_method)
    return result


def build_selection_evidence_snapshot(schedule: dict, project_version_id: int, db: Session) -> dict:
    """Read selected evidence once and return a JSON-safe publication snapshot."""
    course_ids = sorted({
        int(item["course_id"])
        for items in schedule.values()
        for item in items
        if item.get("course_id") is not None
    })
    selection_methods = {
        int(item["course_id"]): str(item.get("selection_method") or "")
        for items in schedule.values()
        for item in items
        if item.get("course_id") is not None
    }
    if not course_ids:
        return {"version": SELECTION_EVIDENCE_SNAPSHOT_VERSION, "courses": {}}
    learning_outcomes = db.query(LearningOutcome).filter(
        LearningOutcome.project_version_id == project_version_id
    ).all()
    lo_by_id = {int(lo.id): lo for lo in learning_outcomes}
    rows = db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version_id,
        MatchScore.course_id.in_(course_ids),
        MatchScore.lo_id.in_(list(lo_by_id) or [-1]),
    ).all()
    return {
        "version": SELECTION_EVIDENCE_SNAPSHOT_VERSION,
        "courses": snapshot_payload(rows, lo_by_id, selection_methods),
    }
