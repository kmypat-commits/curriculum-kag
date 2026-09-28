"""Persistence and read-model assembly at the curriculum publication boundary.

The scheduler owns selection and repair.  This module owns the final durable
Plan/PlanItem write and the semester-level evidence returned to the UI, so the
two concerns cannot quietly drift apart inside one orchestration function.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.bridge_module import BridgeModule
from app.models.embedding import MatchScore
from app.models.plan import Plan, PlanItem
from app.models.project import LearningOutcome, ProjectVersion
from app.planner.joint_contract import PlanningFailure


def persist_plan_result(
    *,
    db: Session,
    project_version_id: int,
    variant_type: str,
    schedule: dict[int, list[dict[str, Any]]],
    metrics: dict[str, Any],
    verification: dict[str, Any],
    commit: bool,
) -> dict[str, Any]:
    """Persist an already-verified schedule and build its bounded UI DTO.

    This intentionally performs no repair and no verification.  Callers must
    pass the exact schedule that was just verified, making the persisted plan
    and returned evidence a single publication boundary.
    """
    version = db.get(ProjectVersion, project_version_id)
    if version is None:
        raise ValueError(f"Project version {project_version_id} not found")
    excluded_ids = {
        int(value)
        for value in (version.project.constraints_json or {}).get("excluded_course_ids", ())
        if str(value).isdigit()
    }
    selected_excluded = sorted({
        int(item["course_id"])
        for items in schedule.values() for item in items
        if item.get("course_id") is not None
        and int(item["course_id"]) in excluded_ids
    })
    if selected_excluded:
        raise PlanningFailure("excluded_course_selected", {
            "course_ids": selected_excluded, "variant": variant_type,
        })
    plan = Plan(
        project_version_id=project_version_id,
        variant_type=variant_type,
        metrics_json=metrics,
    )
    db.add(plan)
    db.flush()
    for semester, courses in schedule.items():
        for item in courses:
            db.add(
                PlanItem(
                    plan_id=plan.id,
                    semester=semester,
                    course_id=item.get("course_id"),
                    bridge_module_id=item.get("bridge_module_id"),
                    credits=item["credits"],
                    course_type=item.get("type", "mandatory"),
                    prerequisites_snapshot=item.get("prerequisites", []),
                )
            )
    if commit:
        db.commit()
        db.refresh(plan)
    else:
        db.flush()

    lo_by_id = {
        lo.id: lo
        for lo in db.query(LearningOutcome)
        .filter(LearningOutcome.project_version_id == project_version_id)
        .all()
    }
    lo_by_code = {lo.lo_code: lo for lo in lo_by_id.values()}
    schedule_course_ids = {
        int(item["course_id"])
        for courses in schedule.values()
        for item in courses
        if item.get("course_id")
    }
    match_rows_by_course: dict[int, list[MatchScore]] = {}
    if schedule_course_ids:
        for row in (
            db.query(MatchScore)
            .filter(
                MatchScore.project_version_id == project_version_id,
                MatchScore.course_id.in_(schedule_course_ids),
            )
            .order_by(MatchScore.course_id, MatchScore.score.desc())
            .all()
        ):
            match_rows_by_course.setdefault(int(row.course_id), []).append(row)
    schedule_bridge_ids = {
        int(item["bridge_module_id"])
        for courses in schedule.values()
        for item in courses
        if item.get("bridge_module_id")
    }
    bridge_by_id = {
        int(module.id): module
        for module in db.query(BridgeModule)
        .filter(BridgeModule.id.in_(schedule_bridge_ids or {-1}))
        .all()
    }

    semester_los: dict[int, str] = {}
    semester_lo_details: dict[int, list[dict[str, Any]]] = {}
    for semester, courses in schedule.items():
        evidence: dict[str, dict[str, Any]] = {}
        for item in courses:
            if item.get("course_id"):
                all_rows = match_rows_by_course.get(int(item["course_id"]), [])
                rows = [row for row in all_rows if row.score >= 0.4] or all_rows[:1]
                for row in rows:
                    lo = lo_by_id.get(row.lo_id)
                    if lo:
                        detail = evidence.setdefault(
                            lo.lo_code,
                            {
                                "code": lo.lo_code,
                                "text": lo.lo_text,
                                "score": 0.0,
                                "courses": [],
                                "kind": "programme",
                            },
                        )
                        detail["score"] = max(detail["score"], round(float(row.score), 3))
                        if item.get("title") not in detail["courses"]:
                            detail["courses"].append(item.get("title"))
            elif item.get("bridge_module_id"):
                bridge = bridge_by_id.get(int(item["bridge_module_id"]))
                for code in (bridge.target_los or []) if bridge else []:
                    lo = lo_by_code.get(code)
                    if lo:
                        detail = evidence.setdefault(
                            code,
                            {
                                "code": code,
                                "text": lo.lo_text,
                                "score": 0.75,
                                "courses": [],
                                "kind": "programme",
                            },
                        )
                        detail["score"] = max(detail["score"], 0.75)
                        if item.get("title") not in detail["courses"]:
                            detail["courses"].append(item.get("title"))
        details = sorted(evidence.values(), key=lambda row: row["code"])
        semester_lo_details[semester] = details
        semester_los[semester] = ", ".join(row["code"] for row in details) if details else "-"

    return {
        "plan_id": plan.id,
        "variant_type": variant_type,
        "schedule": schedule,
        "metrics": metrics,
        "verification": verification,
        "semester_los": semester_los,
        "semester_lo_details": semester_lo_details,
    }
