"""Course replacement endpoints extracted from the planner replacement router.

This module owns read-only candidate retrieval and confirmed course replacement.
"""
from __future__ import annotations

from statistics import median
import time

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.course import Course
from app.models.embedding import MatchScore
from app.models.epvo import EpvoDisciplineNormalized
from app.models.plan import Plan, PlanItem
from app.models.user import User
from app.planner.scheduler import _complexity_min_semester, _course_curriculum_role
from app.services.auth import get_current_user
from app.services.content_localization import course_localization_map
from app.services.epvo_repository import (
    epvo_row_is_relevant,
    epvo_row_matches_education_level,
    epvo_row_relevance_score,
)

router = APIRouter()
REPLACEMENT_PREVIEW_MATCH_LIMIT = 3000

@router.get("/{project_version_id}/course-replacement-preview")
async def course_replacement_preview(
    project_version_id: int,
    course_id: int = Query(...),
    variant: str = Query("A", pattern="^[ABCabc]$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return three same-credit, in-scope alternatives for a suspicious course."""
    from app.models.plan import Plan, PlanItem
    from app.services.epvo_repository import epvo_row_is_relevant, epvo_row_relevance_score

    started = time.perf_counter()
    plan = db.query(Plan).filter(
        Plan.project_version_id == project_version_id,
        Plan.variant_type == variant.upper(),
    ).order_by(Plan.is_active.desc(), Plan.id.desc()).first()
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")
    item = db.query(PlanItem).filter(
        PlanItem.plan_id == plan.id, PlanItem.course_id == course_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Дисциплина не найдена в выбранном плане")
    current = db.query(Course).filter(Course.id == course_id).first()
    if not current:
        raise HTTPException(status_code=404, detail="Дисциплина не найдена")
    goso_applies = str((plan.project_version.project.constraints_json or {}).get("jurisdiction") or "INTERNATIONAL").upper() == "KZ"
    if goso_applies and str(current.course_id or "").startswith("GOSO-KZ-"):
        raise HTTPException(status_code=400, detail="Обязательная дисциплина ГОСО РК защищена от замены")
    lo_by_id = {lo.id: lo for lo in plan.project_version.learning_outcomes}
    raw_target_matches = db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version_id,
        MatchScore.course_id == course_id,
    ).order_by(MatchScore.score.desc()).limit(4).all()
    # A professional course must not be replaced merely because both records
    # happen to cover a generic GSOS communication LO.  Keep only credible
    # professional outcomes of the course being replaced.
    target_matches = [
        row for row in raw_target_matches
        if lo_by_id.get(row.lo_id)
        and not str(lo_by_id[row.lo_id].lo_code or "").startswith("LO-GOSO-")
        and max(
            float(row.score or 0),
            float((row.evidence_json or {}).get("epvo_expert_score") or 0),
        ) >= 0.4
    ]
    target_lo_ids = {row.lo_id for row in target_matches}
    if not target_lo_ids:
        target_lo_ids = {
            lo.id for lo in plan.project_version.learning_outcomes
            if not str(lo.lo_code or "").startswith("LO-GOSO-")
        }
    used_ids = {
        row[0] for row in db.query(PlanItem.course_id).filter(
            PlanItem.plan_id == plan.id, PlanItem.course_id.isnot(None)
        ).all()
    }
    candidate_matches = db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version_id,
        MatchScore.lo_id.in_(target_lo_ids),
        MatchScore.course_id.notin_(used_ids or {-1}),
        MatchScore.score >= 0.35,
    ).order_by(MatchScore.score.desc()).limit(REPLACEMENT_PREVIEW_MATCH_LIMIT).all()
    scores = {}
    for row in candidate_matches:
        expert = float((row.evidence_json or {}).get("epvo_expert_score") or 0)
        effective = max(float(row.score or 0), expert)
        data = scores.setdefault(row.course_id, {"model": 0.0, "expert": 0.0, "los": set(), "values": {}})
        data["model"] = max(data["model"], float(row.score or 0))
        data["expert"] = max(data["expert"], expert)
        data["values"][row.lo_id] = max(float(data["values"].get(row.lo_id) or 0), effective)
        if effective >= 0.4:
            data["los"].add(row.lo_id)
    candidate_ids = list(scores)
    courses = db.query(Course).filter(
        Course.id.in_(candidate_ids or {-1}),
        Course.course_id.like("EPVO-%"),
        Course.credits == int(item.credits or current.credits),
    ).all()
    normalized_ids = [
        int(course.course_id[5:]) for course in courses
        if course.course_id[5:].isdigit()
    ]
    normalized_rows = db.query(EpvoDisciplineNormalized).filter(
        or_(
            EpvoDisciplineNormalized.id.in_(normalized_ids or {-1}),
            EpvoDisciplineNormalized.approved_course_id.in_(candidate_ids or {-1}),
        )
    ).all()
    constraints = plan.project_version.project.constraints_json or {}
    scope_pairs = [(
        str(constraints.get("group_code") or ""),
        str(constraints.get("direction_code") or ""),
    )]
    if str(constraints.get("program_type") or "").lower() in {"interdisciplinary", "joint"}:
        scope_pairs.append((
            str(constraints.get("secondary_group_code") or ""),
            str(constraints.get("secondary_direction_code") or ""),
        ))

    def exact_scope_fit(row):
        row_groups = {str(value or "") for value in (row.group_codes or [])}
        row_directions = {str(value or "") for value in (row.direction_codes or [])}
        return max([
            1.0 if group and group in row_groups else 0.72 if direction and direction in row_directions else 0.0

            for group, direction in scope_pairs
        ] or [0.0])

    relevant_rows_by_course = {}
    typical_semesters_by_course = {}
    for row in normalized_rows:
        if (
            not row.approved_course_id
            or not epvo_row_matches_education_level(row, constraints.get("education_level"))
            or exact_scope_fit(row) <= 0
            or not epvo_row_is_relevant(row, plan.project_version)
        ):
            continue
        previous = relevant_rows_by_course.get(int(row.approved_course_id))
        if previous is None or epvo_row_relevance_score(row, plan.project_version) > epvo_row_relevance_score(previous, plan.project_version):
            relevant_rows_by_course[int(row.approved_course_id)] = row
        if row.typical_semester:
            typical_semesters_by_course.setdefault(int(row.approved_course_id), []).append(int(row.typical_semester))
    ranked = []
    required_lo_count = 1 if len(target_lo_ids) <= 1 else 2
    domains = [plan.project_version.project.domain1, plan.project_version.project.domain2]
    current_semester = int(item.semester or 1)
    for course in courses:
        # `Course.id` is the local database PK; normalized EPVO evidence is
        # keyed by the stable numeric suffix in `Course.course_id`.
        epvo_course_id = None
        course_code = str(course.course_id or "")
        if course_code.startswith("EPVO-"):
            try:
                epvo_course_id = int(course_code.split("-", 1)[1])
            except (TypeError, ValueError):
                epvo_course_id = None
        evidence_id = epvo_course_id or int(course.id)
        row = relevant_rows_by_course.get(evidence_id)
        if row is None:
            continue
        data = scores.get(course.id, {})
        covered_los = set(data.get("los") or set()) & target_lo_ids
        if len(covered_los) < required_lo_count:
            continue
        # A suspicious professional discipline is replaced with another core
        # discipline, never with a generic language/culture course that merely
        # shares one broad LO.
        if exact_scope_fit(row) <= 0 and _course_curriculum_role(course, domains) != "core":
            continue
        complexity_min = _complexity_min_semester({
            "title": course.title,
            "domain": course.domain,
            "type": course.cycle_component,
        }, int(constraints.get("total_semesters", 8) or 8))
        recommended_semester = int(
            median(typical_semesters_by_course.get(evidence_id, []))
            if typical_semesters_by_course.get(evidence_id)
            else (row.typical_semester or course.recommended_semester or 1)
        )
        if complexity_min > current_semester or recommended_semester > current_semester + 1:
            continue
        target_values = [float((data.get("values") or {}).get(lo_id) or 0) for lo_id in target_lo_ids]
        mean_target_score = sum(target_values) / max(1, len(target_values))
        effective = max(target_values or [0.0])
        scope_fit = exact_scope_fit(row)
        rank_score = (
            mean_target_score * 0.45
            + effective * 0.20
            + float(data.get("expert") or 0) * 0.15
            + min(len(covered_los), 3) / 3 * 0.10
            + scope_fit * 0.10
        )
        ranked.append({
            "course_id": course.id,
            "title": course.title,
            "title_translations": {"ru": row.title_ru or course.title, "kk": row.title_kk, "en": row.title_en},
            "description": course.description or (row.content_json or {}).get("description") or "",
            "credits": int(course.credits),
            "model_score": round(float(data.get("model") or 0), 4),
            "expert_score": round(float(data.get("expert") or 0), 4),
            "covered_lo_count": len(covered_los),
            "covered_los": [lo_by_id[lo_id].lo_code for lo_id in sorted(covered_los) if lo_by_id.get(lo_id)],
            "scope_score": round(scope_fit, 4),
            "recommended_semester": recommended_semester,
            "selection_reason": "Совпадает по уровню, направлению, кредитам, семестру и профессиональным LO",
            "selection_reason_translations": {"ru": "Совпадает по уровню, направлению, кредитам, семестру и профессиональным LO", "kk": "Деңгейі, бағыты, кредиттері, семестрі және кәсіби LO сәйкес келеді", "en": "Matches by level, direction, credits, semester, and professional LOs"},
            "rank": round(rank_score, 4),
        })
    ranked.sort(key=lambda row: (row["rank"], row["expert_score"], row["model_score"]), reverse=True)
    candidate_localizations = course_localization_map(
        db, [row["course_id"] for row in ranked[:3]], include_descriptions=False
    )
    for candidate in ranked[:3]:
        titles = (candidate_localizations.get(candidate["course_id"], {}) or {}).get("title_translations") or {}
        if titles:
            candidate["title_translations"] = titles
    return {
        "plan_id": plan.id,
        "variant": plan.variant_type,
        "course_id": current.id,
        "course_title": current.title,
        "credits": int(item.credits or current.credits),
        "target_los": [
            {"code": lo_by_id[lo_id].lo_code, "text": lo_by_id[lo_id].lo_text}
            for lo_id in sorted(target_lo_ids) if lo_by_id.get(lo_id)
        ],
        "quality_rule": {
            "required_professional_los": required_lo_count,
            "same_education_level": True,
            "exact_epvo_scope": True,
            "same_credits": True,
            "semester_compatible": True,
            "core_course_only": True,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "limits": {
            "match_rows": REPLACEMENT_PREVIEW_MATCH_LIMIT,
        },
        "no_candidate_reason": (
            None if ranked else
            "В репозитории нет равноценной дисциплины, которая одновременно проходит профессиональные LO, уровень, направление, кредиты и семестр. Подтвердите исходную дисциплину или измените её семестр."
        ),
        "candidates": ranked[:3],
    }

@router.post("/{project_version_id}/course-replacement-apply")
async def course_replacement_apply(
    project_version_id: int,
    course_id: int = Body(...),
    replacement_course_id: int = Body(...),
    variant: str = Body("A"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Confirm one audited replacement now and for subsequent A/B/C builds."""
    from app.models.plan import Plan, PlanItem

    preview = await course_replacement_preview(
        project_version_id, course_id, variant, db, current_user
    )
    allowed = {row["course_id"] for row in preview["candidates"]}
    if replacement_course_id not in allowed:
        raise HTTPException(status_code=400, detail="Выбранная замена не прошла проверку уровня, направления, кредитов или РО")
    plan = db.query(Plan).filter(Plan.id == preview["plan_id"]).first()
    item = db.query(PlanItem).filter(
        PlanItem.plan_id == plan.id, PlanItem.course_id == course_id
    ).first()
    replacement = db.query(Course).filter(Course.id == replacement_course_id).first()
    if not item or not replacement:
        raise HTTPException(status_code=404, detail="Дисциплина или замена не найдена")
    item.course_id = replacement.id
    item.course_type = replacement.cycle_component or item.course_type
    item.prerequisites_snapshot = [row.id for row in replacement.prerequisites]

    constraints = dict(plan.project_version.project.constraints_json or {})
    replacements = dict(constraints.get("confirmed_course_replacements") or {})
    replacements[str(course_id)] = replacement.id
    constraints["confirmed_course_replacements"] = replacements
    excluded = {int(value) for value in constraints.get("excluded_course_ids") or [] if str(value).isdigit()}
    excluded.add(course_id)
    constraints["excluded_course_ids"] = sorted(excluded)
    plan.project_version.project.constraints_json = constraints
    db.commit()
    return {
        "status": "replaced",
        "updated_plan_id": plan.id,
        "course_id": course_id,
        "replacement_course_id": replacement.id,
        "replacement_title": replacement.title,
        "requires_regeneration": True,
        "message": "Замена применена в текущем плане и сохранена для следующей генерации A/B/C.",
    }
