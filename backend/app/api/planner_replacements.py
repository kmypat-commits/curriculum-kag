from __future__ import annotations

from statistics import median
import time

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.kag.bridge_generator import call_llm
from app.models.audit import AuditEvent
from app.models.bridge_module import BridgeModule
from app.models.course import Course
from app.models.embedding import MatchFeedback, MatchScore
from app.models.epvo import EpvoDisciplineLoLink, EpvoDisciplineNormalized
from app.models.project import ProjectVersion
from app.models.user import User
from app.planner.bridge_suggestions import bridge_candidate_fallbacks as _bridge_candidate_fallbacks
from app.planner.goso import GOSO_COURSE_LO_CODES
from app.planner.planner_utils import (
    compact_lo_label as _compact_lo_label,
    course_display_title as _course_display_title,
    goso_definition_code as _goso_definition_code,
    title_key as _title_key,
)
from app.planner.scheduler import (
    _complexity_min_semester,
    _course_curriculum_role,
    calculate_plan_metrics,
)
from app.services.auth import get_current_user
from app.services.content_localization import (
    bridge_title_translations,
    course_localization_map,
    course_translations,
    course_translation_status,
)
from app.services.epvo_repository import epvo_row_matches_education_level
from app.services.plan_reporting import academic_classification as _academic_classification
from app.api.planner_replacement_courses import course_replacement_preview as _course_replacement_preview


router = APIRouter()
REPLACEMENT_PREVIEW_CANDIDATE_LIMIT = 1500
REPLACEMENT_PREVIEW_MATCH_LIMIT = 3000


@router.get("/{project_version_id}/bridge-replacement-preview")
async def bridge_replacement_preview(
    project_version_id: int,
    variant: str = Query("A"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Suggest real EPVO courses that could replace bridge modules. Read-only."""
    from app.models.plan import Plan, PlanItem
    from app.models.project import LearningOutcome

    started = time.perf_counter()
    plan = db.query(Plan).filter(
        Plan.project_version_id == project_version_id,
        Plan.variant_type == variant.upper(),
    ).order_by(Plan.is_active.desc(), Plan.id.desc()).first()
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")
    project = plan.project_version.project
    constraints = project.constraints_json or {}
    program_type = str(constraints.get("program_type") or "standard").lower()
    interdisciplinary = program_type in {"interdisciplinary", "joint"}
    group_codes = {
        str(value or "").strip()
        for value in (constraints.get("group_code"), constraints.get("secondary_group_code"))
        if str(value or "").strip()
    }
    direction_codes = {
        str(value or "").strip()
        for value in (constraints.get("direction_code"), constraints.get("secondary_direction_code"))
        if str(value or "").strip()
    }
    primary_groups = {str(constraints.get("group_code") or "").strip()}
    secondary_groups = {str(constraints.get("secondary_group_code") or "").strip()}
    primary_directions = {str(constraints.get("direction_code") or "").strip()}
    secondary_directions = {str(constraints.get("secondary_direction_code") or "").strip()}
    primary_groups.discard(""); secondary_groups.discard("")
    primary_directions.discard(""); secondary_directions.discard("")
    items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
    selected_course_ids = {item.course_id for item in items if item.course_id}
    selected_titles = {
        _title_key(course.title)
        for course in db.query(Course).filter(Course.id.in_(selected_course_ids or {-1})).all()
    }
    bridge_items = [item for item in items if item.bridge_module_id]
    bridges_by_id = {
        bridge.id: bridge
        for bridge in db.query(BridgeModule).filter(
            BridgeModule.id.in_([item.bridge_module_id for item in bridge_items] or [-1])
        ).all()
    }
    lo_by_code = {
        lo.lo_code: lo
        for lo in db.query(LearningOutcome).filter(LearningOutcome.project_version_id == project_version_id).all()
    }
    scored_candidate_ids = {
        int(row[0])
        for row in db.query(MatchScore.course_id, func.max(MatchScore.score).label("max_score")).filter(
            MatchScore.project_version_id == project_version_id,
            MatchScore.score >= 0.4,
        ).group_by(MatchScore.course_id).order_by(func.max(MatchScore.score).desc()).limit(REPLACEMENT_PREVIEW_CANDIDATE_LIMIT).all()
    }
    candidate_courses = db.query(Course).filter(
        Course.course_id.like("EPVO-%"),
        Course.id.in_(scored_candidate_ids or {-1}),
        ~Course.id.in_(selected_course_ids or {-1}),
    ).all()
    candidate_ids = [course.id for course in candidate_courses]
    scores_by_course = {}
    if candidate_ids:
        for match in db.query(MatchScore).filter(
            MatchScore.project_version_id == project_version_id,
            MatchScore.course_id.in_(candidate_ids),
            MatchScore.score >= 0.4,
        ).order_by(MatchScore.score.desc()).limit(REPLACEMENT_PREVIEW_MATCH_LIMIT).all():
            scores_by_course.setdefault(match.course_id, []).append(match)
    rows_by_course_id = {}
    if candidate_ids:
        for row in db.query(EpvoDisciplineNormalized).filter(
            EpvoDisciplineNormalized.approved_course_id.in_(candidate_ids)
        ).all():
            rows_by_course_id.setdefault(int(row.approved_course_id), []).append(row)

    suggestions = []
    for item in bridge_items:
        bridge = bridges_by_id.get(item.bridge_module_id)
        if not bridge:
            continue
        # ГОСО outcomes are already covered by protected mandatory courses.
        # They must never make a professional bridge replacement look more
        # relevant or invite an elective to replace normative evidence.
        target_codes = {
            code for code in (bridge.target_los or [])
            if not str(code).startswith("LO-GOSO-")
        }
        target_lo_ids = {lo_by_code[code].id for code in target_codes if code in lo_by_code}
        bridge_code = str(bridge.course_id or "")
        bridge_text = f"{bridge.title or ''} {getattr(bridge, 'description', '') or ''}".lower()
        medicine_markers = ("медицин", "клинич", "здоров", "пациент", "medicine", "medical", "clinical")
        it_markers = (" it ", "информац", "программ", "алгоритм", "данных", "computer", "software", "digital")
        wants_medicine = any(marker in f" {bridge_text} " for marker in medicine_markers)
        wants_it = any(marker in f" {bridge_text} " for marker in it_markers)
        medicine_foundation = any(marker in bridge_text for marker in ("основы медицины", "medical foundations", "medicine foundations"))
        integration_bridge = (
            bridge_code.startswith("CORE_BRIDGE_")
            or "интеграцион" in bridge_text
            or "integration" in bridge_text
        )
        required_scope = (
            "secondary" if bridge_code.startswith("SECONDARY_")
            else None if integration_bridge and interdisciplinary
            else "secondary" if medicine_foundation or (wants_medicine and not wants_it)
            else "primary" if wants_it and not wants_medicine
            else None
        )
        ranked = []
        for course in candidate_courses:
            if _title_key(course.title) in selected_titles:
                continue
            rows = rows_by_course_id.get(course.id, [])
            matching_rows = []
            for value in rows:
                if not epvo_row_matches_education_level(value, constraints.get("education_level")):
                    continue
                value_groups = set(value.group_codes or [])
                value_directions = set(value.direction_codes or [])
                if group_codes & value_groups or direction_codes & value_directions:
                    matching_rows.append(value)
            row = matching_rows[0] if matching_rows else None
            if row:
                row_groups = set(row.group_codes or [])
                row_directions = set(row.direction_codes or [])
                primary_match = any(
                    primary_groups & set(value.group_codes or [])
                    or primary_directions & set(value.direction_codes or [])
                    for value in matching_rows
                )
                secondary_match = any(
                    secondary_groups & set(value.group_codes or [])
                    or secondary_directions & set(value.direction_codes or [])
                    for value in matching_rows
                )
                in_scope = bool(group_codes & row_groups) or bool(direction_codes & row_directions)
                if not in_scope:
                    continue
                if required_scope == "primary" and not primary_match:
                    continue
                if required_scope == "secondary" and not secondary_match:
                    continue
                # A real course may replace an integration bridge only when its

                # EPVO metadata explicitly belongs to both selected scopes.
                if required_scope is None and interdisciplinary and not (primary_match and secondary_match):
                    continue
                if medicine_foundation:
                    candidate_text = " ".join(
                        str(value or "")
                        for value in (
                            course.title,
                            row.title_ru,
                            row.title_kk,
                            row.title_en,
                        )
                    ).lower()
                    medical_content_markers = (
                        "медицин", "клинич", "анатом", "физиолог", "патолог",
                        "здоров", "пациент", "фармак", "молекул", "клетк",
                        "medical", "clinical", "anatom", "physiolog", "health", "patient",
                    )
                    if not any(marker in candidate_text for marker in medical_content_markers):
                        continue
            matches = [m for m in scores_by_course.get(course.id, []) if m.lo_id in target_lo_ids]
            if not matches:
                continue
            expert_score = max(((m.evidence_json or {}).get("epvo_expert_score") or 0) for m in matches)
            model_score = max(float(m.score or 0) for m in matches)
            covered = len({m.lo_id for m in matches})
            coverage_ratio = covered / max(len(target_lo_ids), 1)
            credit_distance = abs(int(course.credits or 0) - int(item.credits or 0))
            combined_score = model_score * 0.55 + float(expert_score or 0) * 0.45
            candidate_text_for_medium = " ".join(
                str(value or "")
                for value in (
                    course.title,
                    course.description,
                    row.title_ru if row else "",
                    row.title_en if row else "",
                    row.title_kk if row else "",
                )
            ).lower()
            generic_social_marker = any(marker in candidate_text_for_medium for marker in (
                "социально-полит", "финансовой грамотности", "антикоррупц",
                "инклюзив", "экология и устойчив", "безопасность жизнедеятельности",
            ))
            professional_marker = any(marker in candidate_text_for_medium for marker in (
                "информац", "цифр", "программ", "алгоритм", "данн",
                "кибер", "безопас", "модель", "искусствен", "intelligence",
                "software", "digital", "algorithm",
            ))
            exact_expert_strong = (
                model_score >= 0.6
                and float(expert_score or 0) >= 0.5
                and credit_distance <= 2
                and coverage_ratio >= 0.75
            )
            focused_model_strong = (
                not generic_social_marker
                and professional_marker
                and model_score >= 0.8
                and float(expert_score or 0) >= 0.15
                and credit_distance <= 2
                and covered >= min(2, max(len(target_lo_ids), 1))
                and coverage_ratio >= 0.5
            )
            strong_candidate = exact_expert_strong or focused_model_strong
            medium_candidate = (
                not strong_candidate
                and not generic_social_marker
                and model_score >= 0.55
                and coverage_ratio >= 0.5
                and credit_distance <= 3
                and (float(expert_score or 0) > 0 or professional_marker)
            )
            quality_level = "strong" if strong_candidate else "medium" if medium_candidate else "weak"
            rank = coverage_ratio * 100 + combined_score * 50 + float(expert_score or 0) * 50 - credit_distance * 10
            ranked.append({
                "course_id": course.id,
                "course_code": course.course_id,
                "title": course.title,
                "title_translations": {
                    "ru": (row.title_ru if row else None) or course.title,
                    "kk": row.title_kk if row else None,
                    "en": row.title_en if row else None,
                },
                "description": (
                    course.description
                    or (((row.content_json or {}).get("description")) if row else None)
                    or "Описание в ЕПВО отсутствует; решение принимается по LO, экспертной оценке и области подготовки."
                ),
                "credits": course.credits,
                "covered_los": covered,
                "target_los": sorted(target_codes),
                "model_score": round(model_score, 4),
                "expert_score": round(float(expert_score or 0), 4),
                "combined_score": round(combined_score, 4),
                "coverage_ratio": round(coverage_ratio, 4),
                "strong_candidate": strong_candidate,
                "medium_candidate": medium_candidate,
                "quality_level": quality_level,
                "requires_expert_confirmation": quality_level != "strong",
                "credit_distance": credit_distance,
                "rank": round(rank, 4),
                "scope": required_scope or "interdisciplinary",
            })
        ranked.sort(key=lambda row: row["rank"], reverse=True)
        # Bridge suggestions must use the same canonical localization map as
        # the plan and graph endpoints; otherwise a missing language silently
        # falls back to the Russian Course.title.
        candidate_localizations = course_localization_map(
            db, [row["course_id"] for row in ranked[:3]], include_descriptions=False
        )
        for candidate in ranked[:3]:
            localized = candidate_localizations.get(candidate["course_id"], {})
            titles = localized.get("title_translations") or {}
            if titles:
                candidate["title_translations"] = titles
        suggestions.append({
            "bridge_item_id": item.id,
            "bridge_module_id": bridge.id,
            "bridge_code": bridge_code,
            "bridge_title": bridge.title,
            "semester": item.semester,
            "credits": item.credits,
            "target_los": sorted(target_codes),
            "required_scope": required_scope or "interdisciplinary",
            "candidates": ranked[:3],
        })
    total_bridge_credits = sum(int(item.credits or 0) for item in bridge_items)
    strong_replacements = sum(
        1 for row in suggestions
        if any(candidate.get("strong_candidate") for candidate in row.get("candidates", []))
    )
    medium_replacements = sum(
        1 for row in suggestions
        if any(candidate.get("quality_level") == "medium" for candidate in row.get("candidates", []))
    )
    candidate_replacements = sum(
        1 for row in suggestions
        if row.get("candidates")
    )
    weak_or_missing = max(0, len(suggestions) - strong_replacements)
    return {
        "project_version_id": project_version_id,
        "plan_id": plan.id,
        "variant": plan.variant_type,
        "summary": {
            "bridge_count": len(bridge_items),
            "bridge_credits": total_bridge_credits,
            "with_any_candidate": candidate_replacements,
            "with_strong_candidate": strong_replacements,
            "with_medium_candidate": medium_replacements,

            "without_strong_candidate": weak_or_missing,
            "diagnosis": (
                "Большая доля bridge означает, что система закрыла кредиты и LO временными проектными модулями. "
                "Их нужно заменить реальными дисциплинами ЕПВО там, где есть сильная экспертная/модельная связь."
            ),
        },
        "suggestions": suggestions,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "limits": {
            "candidate_courses": REPLACEMENT_PREVIEW_CANDIDATE_LIMIT,
            "match_rows": REPLACEMENT_PREVIEW_MATCH_LIMIT,
        },
    }


@router.post("/{project_version_id}/bridge-replacement-apply")
async def bridge_replacement_apply(
    project_version_id: int,
    bridge_item_id: int = Body(...),
    course_id: int = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace one bridge item with an approved in-scope EPVO course."""
    from app.models.plan import Plan, PlanItem

    item = db.query(PlanItem).join(Plan).filter(
        PlanItem.id == bridge_item_id,
        Plan.project_version_id == project_version_id,
    ).first()
    if not item or not item.bridge_module_id:
        raise HTTPException(status_code=404, detail="Bridge-модуль плана не найден")
    course = db.query(Course).filter(Course.id == course_id, Course.course_id.like("EPVO-%")).first()
    if not course:
        raise HTTPException(status_code=404, detail="Дисциплина ЕПВО не найдена")
    duplicate = db.query(PlanItem).filter(
        PlanItem.plan_id == item.plan_id,
        PlanItem.course_id == course.id,
        PlanItem.id != item.id,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Эта дисциплина уже есть в выбранном плане")

    preview = await bridge_replacement_preview(
        project_version_id=project_version_id,
        variant=item.plan.variant_type,
        db=db,
        current_user=current_user,
    )
    allowed_strong = {
        candidate["course_id"]
        for row in preview["suggestions"]
        if row["bridge_item_id"] == item.id
        for candidate in row["candidates"]
        if candidate.get("strong_candidate")
    }
    allowed_manual = {
        candidate["course_id"]
        for row in preview["suggestions"]
        if row["bridge_item_id"] == item.id
        for candidate in row["candidates"]
        if candidate.get("quality_level") in {"strong", "medium"}
    }
    if course.id not in allowed_manual:
        raise HTTPException(
            status_code=400,
            detail="Замена слишком слабая: нужна хотя бы средняя связь с LO, близкий объём кредитов и выбранная область ЕПВО",
        )
    manual_confirmation = course.id not in allowed_strong

    previous_bridge_id = item.bridge_module_id
    constraints = dict(item.plan.project_version.project.constraints_json or {})
    confirmed = dict(constraints.get("confirmed_bridge_replacements") or {})
    confirmed[str(previous_bridge_id)] = course.id
    constraints["confirmed_bridge_replacements"] = confirmed
    item.plan.project_version.project.constraints_json = constraints
    db.commit()
    return {
        "status": "replaced",
        "plan_id": item.plan_id,
        "bridge_item_id": item.id,
        "previous_bridge_module_id": previous_bridge_id,
        "course_id": course.id,
        "course_title": course.title,
        "credits": item.credits,
        "manual_confirmation": manual_confirmation,
        "requires_regeneration": True,
        "message": (
            "Средняя замена подтверждена экспертом и добавлена вместо bridge. Перестройте варианты для полного пересчёта метрик."
            if manual_confirmation else
            "Сильная замена добавлена в план вместо bridge-модуля. Перестройте варианты для полного пересчёта метрик."
        ),
    }


@router.get("/{project_version_id}/bridge-ai-candidates")
async def bridge_ai_candidates(
    project_version_id: int,
    bridge_item_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate three named bridge replacements for expert confirmation."""
    import json
    from app.models.plan import Plan, PlanItem

    item = db.query(PlanItem).join(Plan).filter(
        PlanItem.id == bridge_item_id,
        Plan.project_version_id == project_version_id,
    ).first()
    if not item or not item.bridge_module_id:
        raise HTTPException(status_code=404, detail="Bridge-модуль плана не найден")
    bridge = db.query(BridgeModule).filter(BridgeModule.id == item.bridge_module_id).first()
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not bridge or not version:
        raise HTTPException(status_code=404, detail="Данные bridge-модуля не найдены")
    lo_by_code = {lo.lo_code: lo.lo_text for lo in version.learning_outcomes}
    target_los = [
        code for code in (bridge.target_los or [])
        if code in lo_by_code and not str(code or "").startswith("LO-GOSO-")
    ]
    if not target_los:
        target_los = [code for code in (bridge.target_los or []) if code in lo_by_code]
    prompt = f"""Ты проектировщик образовательных программ Казахстана.
Предложи ровно 3 разные реальные дисциплины вместо служебного bridge-модуля.
Название программы: {version.project.title}
Цель программы: {version.project.goal}
Область 1: {version.project.domain1}; область 2: {version.project.domain2}
Bridge: {bridge.title}
Нужные результаты обучения: {json.dumps({code: lo_by_code[code] for code in target_los}, ensure_ascii=False)}
Объём: {int(item.credits or bridge.credits or 5)} кредитов; семестр: {item.semester}.
Дисциплины должны быть академически правдоподобными, соответствовать РО и уровню программы.
Верни JSON: {{"candidates":[{{"title_ru":"...","title_kk":"...","title_en":"...","description_ru":"2-3 предложения","description_kk":"...","description_en":"...","credits":5,"target_los":["LO1"]}}]}}.
Только JSON."""
    raw = call_llm(prompt, {
        "domain1": version.project.domain1,
        "domain2": version.project.domain2,
        "gap_los": [{"lo_code": code, "lo_text": lo_by_code[code]} for code in target_los],
    })
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        payload = {}
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(candidates, list):
        candidates = []
    fallback_titles = _bridge_candidate_fallbacks(version, bridge, target_los, int(item.semester or 1))
    normalized = []
    seen_titles = set()
    for index in range(3):

        row = candidates[index] if index < len(candidates) and isinstance(candidates[index], dict) else {}
        title_ru = str(row.get("title_ru") or row.get("title") or fallback_titles[index]).strip()[:240]
        if _title_key(title_ru) in seen_titles:
            title_ru = fallback_titles[index]
        if _title_key(title_ru) in seen_titles:
            title_ru = f"{fallback_titles[index]} · {target_los[index % max(len(target_los), 1)] if target_los else 'bridge'}"
        seen_titles.add(_title_key(title_ru))
        description_ru = str(row.get("description_ru") or row.get("description") or (
            f"Дисциплина формирует и проверяет результаты {', '.join(target_los)} через прикладной проект, "
            f"связывающий {version.project.domain1} и {version.project.domain2}."
        )).strip()[:3000]
        normalized.append({
            "candidate_id": index + 1,
            "title_ru": title_ru,
            "title_kk": str(row.get("title_kk") or title_ru)[:240],
            "title_en": str(row.get("title_en") or title_ru)[:240],
            "description_ru": description_ru,
            "description_kk": str(row.get("description_kk") or description_ru)[:3000],
            "description_en": str(row.get("description_en") or description_ru)[:3000],
            "credits": max(3, min(6, int(row.get("credits") or item.credits or 5))),
            "target_los": [code for code in (row.get("target_los") or target_los) if code in lo_by_code] or target_los,
        })
    return {
        "bridge_item_id": item.id,
        "bridge_title": bridge.title,
        "semester": item.semester,
        "target_los": target_los,
        "provider": settings.LLM_PROVIDER,
        "model": settings.LLM_MODEL_NAME,
        "candidates": normalized,
    }


@router.post("/{project_version_id}/bridge-ai-replacement-apply")
async def bridge_ai_replacement_apply(
    project_version_id: int,
    bridge_item_id: int = Body(...),
    candidate: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist an expert-confirmed AI proposal and replace one bridge item."""
    import secrets
    from app.models.plan import Plan, PlanItem
    from app.models.project import LearningOutcome

    item = db.query(PlanItem).join(Plan).filter(
        PlanItem.id == bridge_item_id,
        Plan.project_version_id == project_version_id,
    ).first()
    if not item or not item.bridge_module_id:
        raise HTTPException(status_code=404, detail="Bridge-модуль плана не найден")
    bridge = db.query(BridgeModule).filter(BridgeModule.id == item.bridge_module_id).first()
    title = str(candidate.get("title_ru") or "").strip()
    description = str(candidate.get("description_ru") or "").strip()
    if len(title) < 4 or len(description) < 20:
        raise HTTPException(status_code=400, detail="Для подтверждения нужны название и содержательное описание дисциплины")
    credits = int(item.credits or 5)
    course = Course(
        course_id=f"AI-CONFIRMED-{project_version_id}-{secrets.token_hex(5).upper()}",
        title=title[:240],
        domain=item.plan.project_version.project.domain1 or "interdisciplinary",
        credits=credits,
        recommended_semester=item.semester,
        description=description[:3000],
        topics=[],
        learning_outcomes=[],
        assessment_methods=["практический проект", "экспертная защита"],
        language="ru",
        cycle_component="обязательный компонент (подтверждено экспертом)",
    )
    db.add(course)
    db.flush()
    target_codes = set(candidate.get("target_los") or (bridge.target_los if bridge else []) or [])
    los = db.query(LearningOutcome).filter(
        LearningOutcome.project_version_id == project_version_id,
        LearningOutcome.lo_code.in_(target_codes or {"__none__"}),
    ).all()
    for lo in los:
        db.add(MatchScore(
            project_version_id=project_version_id,
            course_id=course.id,
            lo_id=lo.id,
            score=0.7,
            model_name="llm_bridge_candidate",
            model_version=settings.LLM_MODEL_NAME,
            evidence_json={
                "source": "expert_confirmed_ai_proposal",
                "confirmed_by_user_id": current_user.id,
                "target_lo": lo.lo_code,
                "description": description[:800],
            },
            graph_path_json=[],
        ))
        db.add(MatchFeedback(
            project_version_id=project_version_id,
            course_id=course.id,
            lo_id=lo.id,
            verdict="confirmed",
            corrected_score=0.7,
            comment="Эксперт подтвердил предложенную дисциплину вместо bridge-модуля.",
            user_id=current_user.id,
            model_snapshot_json={"provider": settings.LLM_PROVIDER, "model": settings.LLM_MODEL_NAME},
        ))
    previous_bridge_id = item.bridge_module_id
    item.course_id = course.id
    item.bridge_module_id = None
    item.credits = credits
    item.course_type = course.cycle_component
    item.prerequisites_snapshot = []
    constraints = dict(item.plan.project_version.project.constraints_json or {})
    replacements = dict(constraints.get("confirmed_bridge_replacements") or {})
    replacements[str(previous_bridge_id)] = course.id
    constraints["confirmed_bridge_replacements"] = replacements
    item.plan.project_version.project.constraints_json = constraints
    db.commit()
    return {
        "status": "confirmed",
        "course_id": course.id,
        "course_title": course.title,
        "previous_bridge_module_id": previous_bridge_id,
        "requires_regeneration": True,
        "message": "Предложенная дисциплина подтверждена и заменит bridge при следующем построении A/B/C.",
    }


@router.post("/{project_version_id}/bridge-replacement-apply-all")
async def bridge_replacement_apply_all(
    project_version_id: int,
    variant: str = Body("A"),
    selected_replacements: list[dict] | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atomically replace every bridge that has a sufficiently strong, unique EPVO candidate."""
    from app.models.plan import Plan, PlanItem

    preview = await bridge_replacement_preview(
        project_version_id=project_version_id,
        variant=variant,
        db=db,
        current_user=current_user,
    )
    plan = db.query(Plan).filter(
        Plan.id == preview["plan_id"],
        Plan.project_version_id == project_version_id,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")


    items = {item.id: item for item in db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()}
    used_course_ids = {item.course_id for item in items.values() if item.course_id}
    candidate_ids = {
        candidate["course_id"]
        for row in preview["suggestions"]
        for candidate in row["candidates"]
        if candidate.get("strong_candidate")
    }
    courses = {
        course.id: course
        for course in db.query(Course).filter(
            Course.id.in_(candidate_ids or {-1}),
            Course.course_id.like("EPVO-%"),
        ).all()
    }
    requested = {
        int(row.get("bridge_item_id")): int(row.get("course_id"))
        for row in (selected_replacements or [])
        if str(row.get("bridge_item_id") or "").isdigit()
        and str(row.get("course_id") or "").isdigit()
    }
    if selected_replacements is not None and not requested:
        raise HTTPException(status_code=400, detail="Выберите минимум одну замену")
    replacements = []
    skipped = []
    for row in preview["suggestions"]:
        item = items.get(row["bridge_item_id"])
        if requested and row["bridge_item_id"] not in requested:
            continue
        if not item or not item.bridge_module_id:
            skipped.append({"bridge_item_id": row["bridge_item_id"], "reason": "bridge_not_found"})
            continue
        requested_course_id = requested.get(row["bridge_item_id"])
        candidate = next((
            value for value in row["candidates"]
            if value.get("strong_candidate")
            and value["course_id"] not in used_course_ids
            and value["course_id"] in courses
            and (requested_course_id is None or value["course_id"] == requested_course_id)
        ), None)
        if not candidate:
            skipped.append({"bridge_item_id": item.id, "bridge_title": row["bridge_title"], "reason": "no_unique_strong_candidate"})
            continue
        course = courses[candidate["course_id"]]
        previous_bridge_id = item.bridge_module_id
        used_course_ids.add(course.id)
        item.course_id = course.id
        item.bridge_module_id = None
        item.credits = int(course.credits or item.credits)
        item.course_type = course.cycle_component
        item.prerequisites_snapshot = []
        replacements.append({
            "bridge_item_id": item.id,
            "previous_bridge_module_id": previous_bridge_id,
            "course_id": course.id,
            "course_title": course.title,
            "credits": int(item.credits or course.credits or 0),
        })

    if replacements:
        constraints = dict(plan.project_version.project.constraints_json or {})
        confirmed = dict(constraints.get("confirmed_bridge_replacements") or {})
        for replacement in replacements:
            confirmed[str(replacement["previous_bridge_module_id"])] = replacement["course_id"]
        constraints["confirmed_bridge_replacements"] = confirmed
        plan.project_version.project.constraints_json = constraints
        plan.metrics_json = dict(plan.metrics_json or {})
        db.commit()
    return {
        "status": "replaced" if replacements else "no_candidates",
        "plan_id": plan.id,
        "variant": plan.variant_type,
        "replaced_count": len(replacements),
        "skipped_count": len(skipped),
        "replacements": replacements,
        "skipped": skipped,
        "requires_regeneration": bool(replacements),
        "metrics_recalculated": False,
        "metrics": None,
        "message": (
            f"Заменено bridge-модулей в текущем плане: {len(replacements)}. Перегенерируйте A/B/C для полного пересчёта метрик."
            if replacements else
            "Сильных уникальных замен пока нет. Bridge-модули оставлены без изменений."
        ),
    }


@router.post("/{project_version_id}/course-exclusions")
async def update_course_exclusion(
    project_version_id: int,
    course_id: int = Body(...),
    excluded: bool = Body(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist a course exclusion for subsequent A/B/C regeneration."""
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Версия проекта не найдена")
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Дисциплина не найдена")
    goso_applies = str((version.project.constraints_json or {}).get("jurisdiction") or "INTERNATIONAL").upper() == "KZ"
    if excluded and goso_applies and str(course.course_id or "").startswith("GOSO-KZ-"):
        raise HTTPException(status_code=400, detail="Обязательную дисциплину ГОСО РК нельзя удалить или заменить")
    constraints = dict(version.project.constraints_json or {})
    excluded_ids = {
        int(value) for value in (constraints.get("excluded_course_ids") or [])
        if str(value).isdigit()
    }
    if excluded:
        excluded_ids.add(course.id)
    else:
        excluded_ids.discard(course.id)
    constraints["excluded_course_ids"] = sorted(excluded_ids)
    version.project.constraints_json = constraints
    db.add(AuditEvent(
        user_id=current_user.id,
        action="exclude_course_from_regeneration" if excluded else "restore_course_for_regeneration",
        entity_type="course",
        entity_id=course.id,
        details_json={
            "project_version_id": project_version_id,
            "course_title": course.title,
            "excluded": excluded,
        },
    ))
    db.commit()
    return {
        "course_id": course.id,
        "course_title": course.title,
        "excluded": excluded,
        "excluded_course_ids": sorted(excluded_ids),
        "requires_regeneration": True,
        "message": (
            "Дисциплина отмечена для исключения. При следующем построении A/B/C она не попадёт в планы."
            if excluded else
            "Исключение снято. Дисциплина снова может участвовать в следующем построении."
        ),
    }


@router.post("/{project_version_id}/confirm-suspicious-course")
async def confirm_suspicious_course(
    project_version_id: int,
    course_id: int = Body(...),
    reason: str = Body("expert_confirmed"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    """Expert-confirm a course that the automatic audit marked as suspicious."""
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Версия проекта не найдена")
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Дисциплина не найдена")
    constraints = dict(version.project.constraints_json or {})
    confirmed = {
        int(value) for value in (constraints.get("confirmed_suspicious_course_ids") or [])
        if str(value).isdigit()
    }
    excluded = {
        int(value) for value in (constraints.get("excluded_course_ids") or [])
        if str(value).isdigit()
    }
    confirmed.add(course.id)
    excluded.discard(course.id)
    constraints["confirmed_suspicious_course_ids"] = sorted(confirmed)
    constraints["excluded_course_ids"] = sorted(excluded)
    version.project.constraints_json = constraints
    db.add(AuditEvent(
        user_id=current_user.id,
        action="confirm_suspicious_course",
        entity_type="course",
        entity_id=course.id,
        details_json={
            "project_version_id": project_version_id,
            "course_title": course.title,
            "reason": reason,
        },
    ))
    db.commit()
    return {
        "status": "confirmed",
        "course_id": course.id,
        "course_title": course.title,
        "confirmed_suspicious_course_ids": sorted(confirmed),
        "excluded_course_ids": sorted(excluded),
        "requires_regeneration": False,
        "message": "Эксперт подтвердил дисциплину. Она останется в плане и больше не будет показываться как сомнительная.",
    }


# Course replacement routes live in planner_replacement_courses.py. Keep the
# legacy helpers temporarily private for backwards-compatible imports.
