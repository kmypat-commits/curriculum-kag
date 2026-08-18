from __future__ import annotations

from statistics import median
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.bridge_module import BridgeModule
from app.models.course import Course
from app.models.embedding import MatchFeedback, MatchScore
from app.models.epvo import EpvoDisciplineLoLink, EpvoDisciplineNormalized
from app.models.project import ProjectVersion
from app.models.user import User
from app.planner.goso import GOSO_COURSE_LO_CODES
from app.planner.planner_utils import (
    compact_lo_label as _compact_lo_label,
    course_display_title as _course_display_title,
    goso_definition_code as _goso_definition_code,
    title_key as _title_key,
)
from app.planner.scheduler import _course_curriculum_role, _complexity_min_semester
from app.services.auth import get_current_user
from app.services.content_localization import (
    bridge_title_translations,
    course_localization_map,
    course_translations,
    course_translation_status,
)
from app.services.epvo_repository import epvo_row_matches_education_level
from app.services.plan_reporting import academic_classification as _academic_classification


router = APIRouter()

@router.get("/{project_version_id}/variants")
async def get_variants(
    project_version_id: int,
    include_descriptions: bool = Query(False),
    include_explanations: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get existing plan variants for a project version"""
    from app.models.plan import Plan, PlanItem
    from app.services.epvo_repository import epvo_row_matches_education_level

    all_plans = db.query(Plan).filter(
        Plan.project_version_id == project_version_id
    ).order_by(Plan.id.desc()).all()

    latest_by_variant = {}
    for plan in all_plans:
        latest_by_variant.setdefault(plan.variant_type, plan)

    plans = sorted(
        latest_by_variant.values(),
        key=lambda p: {"A": 0, "B": 1, "C": 2}.get(p.variant_type, 99)
    )

    plan_ids = [plan.id for plan in plans]
    all_items = db.query(PlanItem).filter(PlanItem.plan_id.in_(plan_ids)).all() if plan_ids else []
    items_by_plan = {}
    for item in all_items:
        items_by_plan.setdefault(item.plan_id, []).append(item)
    all_course_ids = sorted({item.course_id for item in all_items if item.course_id})
    all_bridge_ids = sorted({item.bridge_module_id for item in all_items if item.bridge_module_id})
    all_courses_by_id = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(all_course_ids)).all()
    } if all_course_ids else {}
    all_localizations_by_course = course_localization_map(db, all_course_ids, include_descriptions=include_descriptions)
    all_bridges_by_id = {
        bridge.id: bridge
        for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(all_bridge_ids)).all()
    } if all_bridge_ids else {}
    all_epvo_ids = {
        int(str(course.course_id)[5:])
        for course in all_courses_by_id.values()
        if str(course.course_id or "").startswith("EPVO-")
        and str(course.course_id or "")[5:].isdigit()
    }
    all_epvo_rows = db.query(EpvoDisciplineNormalized).filter(
        or_(
            EpvoDisciplineNormalized.id.in_(all_epvo_ids or {-1}),
            EpvoDisciplineNormalized.approved_course_id.in_(all_course_ids or {-1}),
        )
    ).all() if all_epvo_ids else []
    all_expert_counts = {}
    if all_epvo_rows:
        all_row_ids = [row.id for row in all_epvo_rows]
        all_expert_counts = {
            discipline_id: int(count)
            for discipline_id, count in db.query(
                EpvoDisciplineLoLink.discipline_id,
                func.count(EpvoDisciplineLoLink.id),
            ).filter(
                EpvoDisciplineLoLink.discipline_id.in_(all_row_ids)
            ).group_by(EpvoDisciplineLoLink.discipline_id).all()
        }
    all_matches_by_course = {}
    if all_course_ids:
        for match in db.query(MatchScore).filter(
            MatchScore.project_version_id == project_version_id,
            MatchScore.course_id.in_(all_course_ids),
        ).order_by(MatchScore.course_id, MatchScore.score.desc()).all():
            all_matches_by_course.setdefault(match.course_id, []).append(match)
    latest_feedback_by_pair = {}
    if all_course_ids:
        feedback_rows = db.query(MatchFeedback).filter(
            MatchFeedback.project_version_id == project_version_id,
            MatchFeedback.course_id.in_(all_course_ids),
        ).order_by(MatchFeedback.created_at.desc()).all()
        for feedback in feedback_rows:
            latest_feedback_by_pair.setdefault((feedback.course_id, feedback.lo_id), feedback)
    from app.models.project import LearningOutcome
    lo_by_id = {lo.id: lo for lo in db.query(LearningOutcome).filter(
        LearningOutcome.project_version_id == project_version_id
    ).all()}
    lo_by_code = {lo.lo_code: lo for lo in lo_by_id.values()}

    result = []
    for plan in plans:
        # Optimization: fetch items with course/bridge titles
        items = items_by_plan.get(plan.id, [])
        project = plan.project_version.project
        constraints = project.constraints_json or {}
        confirmed_suspicious_course_ids = {
            int(value) for value in (constraints.get("confirmed_suspicious_course_ids") or [])
            if str(value).isdigit()
        }
        primary_group = str(constraints.get("group_code") or "").strip()
        secondary_group = str(constraints.get("secondary_group_code") or "").strip()
        primary_direction = str(constraints.get("direction_code") or "").strip()
        secondary_direction = str(constraints.get("secondary_direction_code") or "").strip()
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
        domains = [
            (project.domain1 or "").strip(),
            (project.domain2 or "").strip(),
        ]
        domain_breakdown = {
            "domain1": {"label": domains[0], "credits": 0, "min_percent": int(constraints.get("min_domain1_percent") or 0)},
            "domain2": {"label": domains[1], "credits": 0, "min_percent": int(constraints.get("min_domain2_percent") or 0)},
            "bridge": {"label": "Bridge", "credits": 0, "min_percent": 0},
            "other": {"label": "Other", "credits": 0, "min_percent": 0},
        }
        bridge_domain_credits = [0.0, 0.0]

        course_ids = [item.course_id for item in items if item.course_id]
        bridge_ids = [item.bridge_module_id for item in items if item.bridge_module_id]
        course_id_set = set(course_ids)
        bridge_id_set = set(bridge_ids)
        courses_by_id = {cid: course for cid, course in all_courses_by_id.items() if cid in course_id_set}
        bridges_by_id = {bid: bridge for bid, bridge in all_bridges_by_id.items() if bid in bridge_id_set}
        item_by_course_id = {
            int(item.course_id): item
            for item in items
            if item.course_id is not None
        }
        postrequisites_by_course_id = {int(course_id): [] for course_id in course_id_set}
        for item in items:
            if item.course_id is None:
                continue
            for prerequisite_id in item.prerequisites_snapshot or []:
                if prerequisite_id in postrequisites_by_course_id:
                    postrequisites_by_course_id[int(prerequisite_id)].append(int(item.course_id))

        def plan_requisite_payload(course_id: int | None) -> dict:
            if course_id is None:
                return {"prerequisites": [], "postrequisites": []}
            current_item = item_by_course_id.get(int(course_id))
            prerequisite_ids = [
                int(value)
                for value in (current_item.prerequisites_snapshot or [])
                if int(value) in course_id_set
            ] if current_item else []

            def course_ref(value: int) -> dict | None:
                course = courses_by_id.get(int(value))
                plan_item = item_by_course_id.get(int(value))
                if not course or not plan_item:
                    return None
                return {
                    "course_id": course.id,
                    "course_code": course.course_id,
                    "title": _course_display_title(course, f"Дисциплина №{course.id}"),
                    "title_translations": (
                        all_localizations_by_course.get(int(value), {}).get("title_translations", {})
                        or {"ru": _course_display_title(course, f"Дисциплина №{course.id}")}
                    ),
                    "semester": plan_item.semester,
                    "credits": plan_item.credits,
                }

            prerequisites = [
                ref for ref in (course_ref(value) for value in prerequisite_ids)
                if ref is not None
            ]
            postrequisites = [
                ref for ref in (
                    course_ref(value)
                    for value in postrequisites_by_course_id.get(int(course_id), [])
                )
                if ref is not None
            ]
            prerequisites.sort(key=lambda row: (row["semester"], row["title"]))
            postrequisites.sort(key=lambda row: (row["semester"], row["title"]))
            return {
                "prerequisites": prerequisites,
                "postrequisites": postrequisites,
            }

        matches_by_course = {cid: all_matches_by_course.get(cid, []) for cid in course_id_set}
        course_title_keys = {_title_key(course.title) for course in courses_by_id.values()}
        epvo_ids = []
        for course in courses_by_id.values():
            code = course.course_id or ""
            if code.startswith("EPVO-") and code[5:].isdigit():
                epvo_ids.append(int(code[5:]))
        epvo_id_set = set(epvo_ids)
        epvo_rows = [
            row for row in all_epvo_rows
            if row.id in epvo_id_set or row.approved_course_id in course_id_set
        ] if epvo_ids and (group_codes or direction_codes) else []
        epvo_rows_by_id = {row.id: row for row in epvo_rows}
        epvo_row_by_course_id = {
            course.id: epvo_rows_by_id.get(int(course.course_id[5:]))
            for course in courses_by_id.values()
            if str(course.course_id or "").startswith("EPVO-")
            and str(course.course_id or "")[5:].isdigit()
        }
        epvo_level_allowed_course_ids = {
            int(row.approved_course_id)
            for row in epvo_rows
            if row.approved_course_id
            and epvo_row_matches_education_level(row, constraints.get("education_level"))
        }
        expert_counts = all_expert_counts
        epvo_matched_keys = set()
        epvo_expert_links = 0
        course_domain_index = {}
        course_domain_evidence = {}
        for row in epvo_rows:
            if not (
                group_codes.intersection(set(row.group_codes or []))
                or direction_codes.intersection(set(row.direction_codes or []))
            ):
                continue
            keys = {_title_key(value) for value in (row.title_ru, row.title_kk, row.title_en) if value}
            if keys.intersection(course_title_keys):
                epvo_matched_keys.update(keys.intersection(course_title_keys))
                epvo_expert_links += expert_counts.get(row.id, 0)
            row_groups = set(row.group_codes or [])
            row_directions = set(row.direction_codes or [])
            primary_scope = (
                3 if primary_group and primary_group in row_groups
                else 2 if primary_direction and primary_direction in row_directions
                else 0
            )
            secondary_scope = (
                3 if secondary_group and secondary_group in row_groups
                else 2 if secondary_direction and secondary_direction in row_directions
                else 0
            )
            if row.approved_course_id and (primary_scope or secondary_scope):
                evidence = course_domain_evidence.setdefault(int(row.approved_course_id), [0, 0])
                evidence[0] = max(evidence[0], primary_scope)
                evidence[1] = max(evidence[1], secondary_scope)
        course_domain_index = {
            course_id: 1 if secondary_scope > primary_scope else 0
            for course_id, (primary_scope, secondary_scope) in course_domain_evidence.items()
        }
        epvo_course_count = len([item for item in items if item.course_id])
        epvo_plan_quality = {
            "matched_courses": len(epvo_matched_keys),
            "course_count": epvo_course_count,
            "match_percentage": round(len(epvo_matched_keys) / max(epvo_course_count, 1) * 100, 1),
            "expert_links": epvo_expert_links,
        }

        schedule = {}
        suspicious_courses = []
        for item in items:
            if item.semester not in schedule:
                schedule[item.semester] = []

            # Get title
            title = "Неизвестная дисциплина"
            why_selected = None
            academic_metadata = {
                "academic_cycle": None,
                "academic_cycle_source": None,
                "academic_component": "bridge-модуль",
                "protected_by_goso": False,
            }
            if item.course_id:
                course_obj = courses_by_id.get(item.course_id)
                title = _course_display_title(course_obj, f"Дисциплина №{item.course_id}")
                domain = (course_obj.domain or "").lower().strip() if course_obj else ""
                domain1 = domains[0].lower().strip()
                domain2 = domains[1].lower().strip()
                scoped_domain_index = course_domain_index.get(item.course_id)
                if scoped_domain_index == 0 or (
                    scoped_domain_index is None and domain1 and (domain1 in domain or domain in domain1)
                ):
                    domain_breakdown["domain1"]["credits"] += int(item.credits or 0)
                elif scoped_domain_index == 1 or (
                    scoped_domain_index is None and domain2 and (domain2 in domain or domain in domain2)
                ):
                    domain_breakdown["domain2"]["credits"] += int(item.credits or 0)
                else:
                    domain_breakdown["other"]["credits"] += int(item.credits or 0)
                match_rows = matches_by_course.get(item.course_id, [])
                max_score = max([float(row.score or 0) for row in match_rows], default=0.0)
                top_match = max(
                    match_rows,
                    key=lambda row: max(
                        float(row.score or 0),
                        float((row.evidence_json or {}).get("epvo_expert_score") or 0),
                    ),
                    default=None,
                )
                expert_supported = any(((row.evidence_json or {}).get("epvo_expert_score") or 0) > 0 for row in match_rows)
                # A canonical EPVO Course can be reused by many programmes and
                # its legacy domain string may come from the first programme
                # that imported it. Exact membership in either selected EPVO
                # scope is authoritative for the current project.
                role = (
                    "core" if scoped_domain_index in {0, 1}
                    else _course_curriculum_role(course_obj, [domain1, domain2]) if course_obj
                    else "unknown"
                )
                academic_metadata = _academic_classification(
                    course_obj,
                    int(item.semester or 1),
                    int(constraints.get("total_semesters", 8) or 8),
                    role,
                    str(constraints.get("jurisdiction") or "INTERNATIONAL"),
                )
                complexity_min = _complexity_min_semester({
                    "title": title,
                    "domain": course_obj.domain if course_obj else "",
                    "type": course_obj.cycle_component if course_obj else "",
                }, int(constraints.get("total_semesters", 8) or 8))
                reasons = []
                epvo_row = epvo_row_by_course_id.get(item.course_id)
                if epvo_row is not None and item.course_id not in epvo_level_allowed_course_ids:
                    reasons.append("wrong_education_level")
                if role != "core":
                    reasons.append("not_core_for_program")
                if max_score < 0.55 and not expert_supported:
                    reasons.append("weak_lo_evidence")
                if int(item.semester or 1) < complexity_min:
                    reasons.append("too_early_for_complexity")
                high_risk = (
                    "wrong_education_level" in reasons
                    or
                    "too_early_for_complexity" in reasons
                    or ("not_core_for_program" in reasons and "weak_lo_evidence" in reasons)
                )
                if (
                    reasons
                    and high_risk
                    and not academic_metadata["protected_by_goso"]
                    and int(item.course_id) not in confirmed_suspicious_course_ids
                ):
                    reason_details = {
                        "wrong_education_level": "Дисциплина относится к другому уровню образования в ЕПВО.",
                        "not_core_for_program": "Дисциплина не относится к выбранному направлению/группе ОП как ядро программы.",
                        "weak_lo_evidence": "Нет достаточно сильной связи с профессиональными результатами обучения программы.",
                        "too_early_for_complexity": "Дисциплина выглядит слишком сложной для указанного семестра.",
                    }
                    suspicious_courses.append({
                        "course_id": item.course_id,
                        "title": title,
                        "semester": item.semester,
                        "credits": item.credits,
                        "domain": course_obj.domain if course_obj else None,
                        "role": role,
                        "max_score": round(max_score, 4),
                        "expert_supported": expert_supported,
                        "recommended_min_semester": complexity_min,
                        "top_lo_id": top_match.lo_id if top_match else None,
                        "top_lo_code": lo_by_id.get(top_match.lo_id).lo_code if top_match and lo_by_id.get(top_match.lo_id) else None,
                        "top_lo_text": lo_by_id.get(top_match.lo_id).lo_text if top_match and lo_by_id.get(top_match.lo_id) else None,
                        "reasons": reasons,
                        "reason_details": [reason_details.get(reason, reason) for reason in reasons],
                        "recommendation": "Подтвердите связь экспертом, перенесите дисциплину в более поздний семестр или замените её на дисциплину ЕПВО того же уровня и направления.",
                    })
                top_matches = []
                trustworthy_matches = []
                for row in match_rows:
                    evidence = row.evidence_json or {}
                    feedback = latest_feedback_by_pair.get((row.course_id, row.lo_id))
                    expert_score = float(evidence.get("epvo_expert_score") or 0)
                    if feedback and feedback.verdict == "incorrect":
                        continue
                    if float(row.score or 0) >= 0.4 or expert_score >= 0.5 or (feedback and feedback.verdict == "confirmed"):
                        trustworthy_matches.append(row)
                def effective_match_score(row):
                    evidence = row.evidence_json or {}
                    feedback = latest_feedback_by_pair.get((row.course_id, row.lo_id))
                    corrected = float(feedback.corrected_score or 0) if feedback and feedback.verdict == "corrected" else 0.0
                    return max(float(row.score or 0), float(evidence.get("epvo_expert_score") or 0), corrected)

                trustworthy_matches.sort(key=effective_match_score, reverse=True)
                display_matches = trustworthy_matches[:3]
                if not display_matches and match_rows:
                    display_matches = sorted(
                        [
                            row for row in match_rows
                            if not (
                                latest_feedback_by_pair.get((row.course_id, row.lo_id))
                                and latest_feedback_by_pair[(row.course_id, row.lo_id)].verdict == "incorrect"
                            )
                        ],
                        key=effective_match_score,
                        reverse=True,
                    )[:1]
                for row in display_matches:
                    lo = lo_by_id.get(row.lo_id)
                    if not lo:
                        continue
                    evidence = row.evidence_json or {}
                    feedback = latest_feedback_by_pair.get((row.course_id, row.lo_id))
                    ai_score = round(float(row.score or 0), 3)
                    expert_score = evidence.get("epvo_expert_score")
                    corrected_score = float(feedback.corrected_score or 0) if feedback and feedback.verdict == "corrected" else 0.0
                    effective_score = round(max(ai_score, float(expert_score or 0), corrected_score), 3)
                    course_titles = (all_localizations_by_course.get(item.course_id, {}) or {}).get("title_translations", {})
                    title_kk = course_titles.get("kk") or title
                    title_en = course_titles.get("en") or title
                    evidence_label = (
                        "экспертная правка" if corrected_score > 0
                        else "экспертная оценка ЕПВО" if float(expert_score or 0) > 0
                        else "прогноз ИИ по текстам"
                    )
                    top_matches.append({
                        "lo_id": lo.id,
                        "lo_code": lo.lo_code,
                        "lo_text": lo.lo_text,
                        # `score` remains for older clients. The explicit fields
                        # prevent users from adding two independent estimates.
                        "score": effective_score,
                        "effective_score": effective_score,
                        "ai_score": ai_score,
                        "expert_score": expert_score,
                        "explanation": (
                            f"Итог {round(effective_score * 100)}% — сила связи «{title} → {lo.lo_code}». "
                            f"ИИ {round(ai_score * 100)}% — прогноз модели по описанию дисциплины и текста LO. "
                            f"ЕПВО {round(float(expert_score or 0) * 100)}% — похожая экспертная разметка из ЕПВО. "
                            f"Эти проценты не складываются; система берёт наиболее надёжный сигнал: {evidence_label}."
                        ),
                        "explanation_translations": {
                            "ru": (
                                f"Итог {round(effective_score * 100)}% — сила связи «{title} → {lo.lo_code}». "
                                f"ИИ {round(ai_score * 100)}% — прогноз модели по описанию дисциплины и текста LO. "
                                f"ЕПВО {round(float(expert_score or 0) * 100)}% — похожая экспертная разметка из ЕПВО. "
                                f"Эти проценты не складываются; система берёт наиболее надёжный сигнал: {evidence_label}."
                            ),
                            "kk": (
                                f"Қорытынды {round(effective_score * 100)}% — «{title_kk} → {lo.lo_code}» байланысының күші. "
                                f"ЖИ {round(ai_score * 100)}% — пән сипаттамасы мен LO мәтініне негізделген модель болжамы. "
                                f"ЕПВО {round(float(expert_score or 0) * 100)}% — ЕПВО деректеріндегі ұқсас сараптамалық белгі. "
                                "Бұл пайыздар қосылмайды; жүйе ең сенімді сигналды пайдаланады."
                            ),
                            "en": (
                                f"Final {round(effective_score * 100)}% — strength of the «{title_en} → {lo.lo_code}» link. "
                                f"AI {round(ai_score * 100)}% — model prediction from the course description and LO text. "
                                f"EPVO {round(float(expert_score or 0) * 100)}% — similar expert annotation from EPVO. "
                                "These percentages are not added; the system uses the most reliable signal."
                            ),
                        },
                        "weak_evidence": row not in trustworthy_matches,
                        "source": evidence.get("source") or evidence.get("label") or row.model_name,
                        "expert_feedback": (
                            {
                                "verdict": latest_feedback_by_pair[(row.course_id, row.lo_id)].verdict,
                                "corrected_score": latest_feedback_by_pair[(row.course_id, row.lo_id)].corrected_score,
                                "comment": latest_feedback_by_pair[(row.course_id, row.lo_id)].comment,
                            }
                            if (row.course_id, row.lo_id) in latest_feedback_by_pair else None
                        ),
                    })
                sem = item.semester
                domain_name = course_obj.domain if course_obj else None
                domain_ru = domain_name or 'не указан'
                domain_kk = domain_name or 'көрсетілмеген'
                domain_en = domain_name or 'not specified'
                why_selected = {
                    "role": role,
                    "max_score": round(max_score, 4),
                    "expert_supported": expert_supported,
                    "top_lo_matches": top_matches,
                    "semester_reason": f"Семестр {sem}: учтены рекомендуемый семестр, пререквизиты и нагрузка.",
                    "semester_reason_translations": {
                        "ru": f"Семестр {sem}: учтены рекомендуемый семестр, пререквизиты и нагрузка.",
                        "kk": f"{sem}-семестр: ұсынылатын семестр, пререквизиттер және жүктеме ескерілді.",
                        "en": f"Semester {sem}: recommended semester, prerequisites, and load considered.",
                    },
                    "domain_reason": f"Домен дисциплины: {domain_ru}.",
                    "domain_reason_translations": {
                        "ru": f"Домен дисциплины: {domain_ru}.",
                        "kk": f"Пән домені: {domain_kk}.",
                        "en": f"Course domain: {domain_en}.",
                    },
                    "selection_reason": (
                        f"Наиболее сильная связь — {top_matches[0]['lo_code']}: итоговая уверенность {round(top_matches[0]['effective_score'] * 100)}%. Оценки ИИ и ЕПВО относятся к одной паре «дисциплина → результат обучения» и не складываются."
                        if top_matches else "Дисциплина включена для структуры, кредитов или доменной целостности плана."
                    ),
                    "selection_reason_translations": (
                        {
                            "ru": f"Наиболее сильная связь — {top_matches[0]['lo_code']}: итоговая уверенность {round(top_matches[0]['effective_score'] * 100)}%. Оценки ИИ и ЕПВО относятся к одной паре «дисциплина → результат обучения» и не складываются.",
                            "kk": f"Ең күшті байланыс — {top_matches[0]['lo_code']}: қорытынды сенімділік {round(top_matches[0]['effective_score'] * 100)}%. ЖИ және ЕПВО бағалары бір «пән → оқу нәтижесі» жұбына жатады және қосылмайды.",
                            "en": f"Strongest link — {top_matches[0]['lo_code']}: effective confidence {round(top_matches[0]['effective_score'] * 100)}%. AI and EPVO scores refer to the same «course → learning outcome» pair and are not additive.",
                        }
                        if top_matches else {
                            "ru": "Дисциплина включена для структуры, кредитов или доменной целостности плана.",
                            "kk": "Пән жоспардың құрылымы, кредиттері немесе домендік тұтастығы үшін қосылды.",
                            "en": "Course included for structure, credits, or domain integrity of the plan.",
                        }
                    ),
                }
            elif item.bridge_module_id:
                bm_obj = bridges_by_id.get(item.bridge_module_id)
                title = bm_obj.title if bm_obj else f"Bridge-модуль №{item.bridge_module_id}"
                domain_breakdown["bridge"]["credits"] += int(item.credits or 0)
                bridge_code = str(bm_obj.course_id or "") if bm_obj else ""
                bridge_credits = float(item.credits or 0)
                if bridge_code.startswith("SECONDARY_"):
                    bridge_domain_credits[1] += bridge_credits
                elif bridge_code.startswith("CORE_BRIDGE_"):
                    bridge_domain_credits[0] += bridge_credits / 2.0
                    bridge_domain_credits[1] += bridge_credits / 2.0
                bridge_sem = item.semester
                why_selected = {
                    "role": "bridge",
                    "max_score": 0.75,
                    "expert_supported": True,
                    "top_lo_matches": [
                        {"lo_code": code, "lo_text": lo_by_code.get(code).lo_text if lo_by_code.get(code) else code, "score": 0.75, "effective_score": 0.75, "ai_score": None, "expert_score": None, "source": "bridge_target"}
                        for code in (bm_obj.target_los or [])[:3]
                    ] if bm_obj else [],
                    "semester_reason": f"Семестр {bridge_sem}: bridge-модуль размещён для закрытия междисциплинарного/кредитного пробела.",
                    "semester_reason_translations": {
                        "ru": f"Семестр {bridge_sem}: bridge-модуль размещён для закрытия междисциплинарного/кредитного пробела.",
                        "kk": f"{bridge_sem}-семестр: bridge-модуль пәнаралық/кредиттік олқылықты жабу үшін орналастырылды.",
                        "en": f"Semester {bridge_sem}: bridge module placed to close interdisciplinary/credit gap.",
                    },
                    "domain_reason": "Bridge-модуль относится к междисциплинарной части плана.",
                    "domain_reason_translations": {
                        "ru": "Bridge-модуль относится к междисциплинарной части плана.",
                        "kk": "Bridge-модуль жоспардың пәнаралық бөлігіне жатады.",
                        "en": "Bridge module belongs to the interdisciplinary part of the plan.",
                    },
                    "selection_reason": "Bridge-модуль добавлен системой для усиления связей между областями и результатами обучения.",
                    "selection_reason_translations": {
                        "ru": "Bridge-модуль добавлен системой для усиления связей между областями и результатами обучения.",
                        "kk": "Bridge-модуль жүйе тарапынан салалар мен оқу нәтижелері арасындағы байланыстарды күшейту үшін қосылды.",
                        "en": "Bridge module added by the system to strengthen links between domains and learning outcomes.",
                    },
                }

            schedule[item.semester].append({
                "course_id": item.course_id,
                **academic_metadata,
                "course_code": course_obj.course_id if item.course_id and course_obj else None,
                "course_source": (
                    "rk_mandatory" if academic_metadata["protected_by_goso"]
                    else "ai_confirmed" if item.course_id and course_obj and str(course_obj.course_id or "").startswith("AI-CONFIRMED-")
                    else "repository" if item.course_id else "bridge"
                ),
                "bridge_module_id": item.bridge_module_id,
                "title": title,
                "title_translations": (
                    bridge_title_translations(title)
                    if item.bridge_module_id
                    else {"ru": title, "kk": title, "en": title}
                    if item.course_id and course_obj and _goso_definition_code(course_obj)
                    else all_localizations_by_course.get(item.course_id, {}).get("title_translations", {})
                    if item.course_id else bridge_title_translations(title)
                ),
                "description": course_obj.description if include_descriptions and item.course_id and course_obj else None,
                "description_translations": all_localizations_by_course.get(item.course_id, {}).get("description_translations", {}) if include_descriptions and item.course_id else {},
                "translation_status": all_localizations_by_course.get(item.course_id, {}).get("translation_status") if item.course_id else None,
                "credits": item.credits,
                "type": item.course_type,
                # Keep the academic component as metadata. It must never be
                # used in place of the actual discipline title in the UI.
                "cycle_component": (
                    course_obj.cycle_component if item.course_id and course_obj
                    else item.course_type
                ),
                # Explanations contain full LO text and are large for A/B/C.
                # Return them only when the user explicitly requests details.
                "why_selected": why_selected if include_explanations else None,
                "plan_requisites": plan_requisite_payload(item.course_id) if include_explanations else None,
            })

        # Add semester LOs
        semester_los = {}
        semester_lo_details = {}
        for sem, courses in schedule.items():
            evidence = {}
            for c in courses:
                if c.get("course_id"):
                    # Find LOs covered by this course in this project version
                    all_matches = matches_by_course.get(c["course_id"], [])
                    matches = []
                    for row in all_matches:
                        feedback = latest_feedback_by_pair.get((row.course_id, row.lo_id))
                        expert_score = float((row.evidence_json or {}).get("epvo_expert_score") or 0)
                        if feedback and feedback.verdict == "incorrect":
                            continue
                        if float(row.score or 0) >= 0.4 or expert_score >= 0.5 or (feedback and feedback.verdict == "confirmed"):
                            matches.append(row)
                    for m in matches:
                        lo = lo_by_id.get(m.lo_id)
                        if lo:
                            row = evidence.setdefault(lo.lo_code, {
                                "code": lo.lo_code, "text": lo.lo_text,
                                "score": 0.0, "courses": [], "kind": "programme",
                            })
                            row["score"] = max(row["score"], round(float(m.score), 3))
                            if c["title"] not in row["courses"]:
                                row["courses"].append(c["title"])
                elif c.get("bridge_module_id"):
                    bridge = bridges_by_id.get(c["bridge_module_id"])
                    for code in (bridge.target_los or []) if bridge else []:
                        lo = lo_by_code.get(code)
                        if lo:
                            row = evidence.setdefault(code, {
                                "code": code, "text": lo.lo_text,
                                "score": 0.75, "courses": [], "kind": "programme",
                            })
                            row["score"] = max(row["score"], 0.75)
                            if c["title"] not in row["courses"]:
                                row["courses"].append(c["title"])

            details = sorted(evidence.values(), key=lambda row: row["code"])
            if not details:
                course_outcomes = []
                for c in courses:
                    if c.get("course_id"):
                        entity = courses_by_id.get(c["course_id"])
                    else:
                        entity = bridges_by_id.get(c.get("bridge_module_id"))
                    for outcome in (entity.learning_outcomes or []) if entity else []:
                        clean = str(outcome).strip()
                        if clean and clean not in [row["text"] for row in course_outcomes]:
                            course_outcomes.append({
                                "code": f"CLO{len(course_outcomes) + 1}",
                                "text": clean, "score": None,
                                "courses": [c["title"]], "kind": "course",
                            })
                        if len(course_outcomes) >= 8:
                            break
                    if len(course_outcomes) >= 8:
                        break
                details = course_outcomes
            semester_lo_details[sem] = details
            semester_los[sem] = ", ".join(row["code"] for row in details) if details else "-"

        metrics = plan.metrics_json or {}
        from app.planner.plan_metrics import persisted_metrics_current
        total_breakdown_credits = max(1, sum(item["credits"] for item in domain_breakdown.values()))
        domain_breakdown["domain1"]["quota_credits"] = round(
            domain_breakdown["domain1"]["credits"] + bridge_domain_credits[0], 1
        )
        domain_breakdown["domain2"]["quota_credits"] = round(
            domain_breakdown["domain2"]["credits"] + bridge_domain_credits[1], 1
        )
        domain_breakdown["bridge"]["quota_credits"] = domain_breakdown["bridge"]["credits"]
        domain_breakdown["other"]["quota_credits"] = domain_breakdown["other"]["credits"]
        for item in domain_breakdown.values():
            item["percent"] = round(float(item.get("quota_credits", item["credits"])) / total_breakdown_credits * 100, 1)
        result.append({
            "plan_id": plan.id,
            "variant_type": plan.variant_type,
            "is_active": plan.is_active == 1,
            "metrics": metrics,
            "metrics_current": persisted_metrics_current(metrics),
            "verification": metrics.get("verification", {}),
            "schedule": schedule,
            "semester_los": semester_los,
            "semester_lo_details": semester_lo_details,
            "domain_breakdown": domain_breakdown,
            "epvo_plan_quality": epvo_plan_quality,
            "suspicious_courses": suspicious_courses,
        })

    # Expose the same deterministic fingerprint used by the build endpoint.
    # This makes legacy duplicate A/B/C variants visible in the UI instead of
    # silently presenting cosmetic labels as independent alternatives.
    fingerprints = {}
    for row in result:
        signature = []
        schedule = row.get("schedule") or {}
        for semester, semester_items in sorted(schedule.items(), key=lambda pair: int(pair[0])):
            for item in semester_items or []:
                if not isinstance(item, dict):
                    continue
                signature.append((int(semester), item.get("course_id"), item.get("bridge_module_id")))
        fingerprint = "|".join(
            f"{semester}:{course_id or ''}:{bridge_id or ''}"
            for semester, course_id, bridge_id in signature
        )
        row["schedule_fingerprint"] = fingerprint
        fingerprints.setdefault(fingerprint, []).append(row.get("variant_type"))
    for row in result:
        duplicate_variants = fingerprints.get(row.get("schedule_fingerprint"), [])
        row["variant_distinct"] = len(duplicate_variants) <= 1
        row["duplicate_variants"] = duplicate_variants if len(duplicate_variants) > 1 else []
    return result


@router.get("/{project_version_id}/lo-coverage-sources")
async def lo_coverage_sources(
    project_version_id: int,
    variant: str = Query("A"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Explain which LOs are covered by real courses and which by bridge modules."""
    from app.models.plan import Plan, PlanItem
    from app.models.project import LearningOutcome

    started = time.perf_counter()
    plan = db.query(Plan).filter(
        Plan.project_version_id == project_version_id,
        Plan.variant_type == variant.upper(),
    ).order_by(Plan.is_active.desc(), Plan.id.desc()).first()
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")
    items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
    course_ids = [item.course_id for item in items if item.course_id]
    bridge_ids = [item.bridge_module_id for item in items if item.bridge_module_id]
    courses = {course.id: course for course in db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()}
    bridges = {bridge.id: bridge for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids or [-1])).all()}
    los = db.query(LearningOutcome).filter(LearningOutcome.project_version_id == project_version_id).order_by(LearningOutcome.order_index, LearningOutcome.id).all()

    course_matches = {}
    if course_ids:
        for match in db.query(MatchScore).filter(
            MatchScore.project_version_id == project_version_id,
            MatchScore.course_id.in_(course_ids),
            MatchScore.score >= 0.4,
        ).order_by(MatchScore.score.desc()).all():
            by_course = course_matches.setdefault(match.lo_id, {})
            current = by_course.get(match.course_id)
            current_score = max(
                float(current.score or 0) if current else 0.0,
                float((current.evidence_json or {}).get("epvo_expert_score") or 0) if current else 0.0,
            )
            candidate_score = max(
                float(match.score or 0),
                float((match.evidence_json or {}).get("epvo_expert_score") or 0),
            )
            if current is None or candidate_score > current_score:
                by_course[match.course_id] = match

    result = []
    for lo in los:
        real_sources = []
        seen_real_course_ids = set()
        # Mandatory ГОСО courses have an explicit normative LO mapping and do
        # not need a probabilistic MatchScore row.  Treat them as real,
        # auditable evidence so the UI does not falsely report a bridge-only
        # gap for languages, history, practices or final attestation.
        for item in items:
            if not item.course_id:
                continue
            course = courses.get(item.course_id)
            code = str(course.course_id or "") if course else ""
            if not code.startswith("GOSO-KZ-"):
                continue
            definition_code = code.removeprefix("GOSO-KZ-")
            if GOSO_COURSE_LO_CODES.get(definition_code) != lo.lo_code:
                continue
            seen_real_course_ids.add(course.id)
            real_sources.append({
                "course_id": course.id,
                "title": _course_display_title(course),
                "credits": item.credits,
                "semester": item.semester,
                "score": 1.0,
                "expert_score": 0.0,
                "source": "goso_regulatory",
            })
        lo_matches = sorted(
            course_matches.get(lo.id, {}).values(),
            key=lambda match: max(
                float(match.score or 0),
                float((match.evidence_json or {}).get("epvo_expert_score") or 0),
            ),
            reverse=True,
        )
        for match in lo_matches[:8]:
            course = courses.get(match.course_id)
            if not course or course.id in seen_real_course_ids:
                continue
            seen_real_course_ids.add(course.id)
            evidence = match.evidence_json or {}
            real_sources.append({
                "course_id": course.id,
                "title": _course_display_title(course),
                "credits": course.credits,
                "score": round(float(match.score or 0), 4),
                "expert_score": round(float(evidence.get("epvo_expert_score") or 0), 4),
                "source": evidence.get("source") or "model",
            })
        bridge_sources = []
        seen_bridge_ids = set()
        for item in items:
            if not item.bridge_module_id:
                continue
            bridge = bridges.get(item.bridge_module_id)
            if bridge and bridge.id not in seen_bridge_ids and lo.lo_code in (bridge.target_los or []):
                seen_bridge_ids.add(bridge.id)
                bridge_sources.append({
                    "bridge_id": bridge.id,
                    "plan_item_id": item.id,
                    "title": bridge.title,
                    "credits": item.credits,
                    "semester": item.semester,
                    "score": 0.75,
                    "source_label": "Bridge-модуль находится в выбранном плане",
                })
        regulatory_evidence = any(row.get("source") == "goso_regulatory" for row in real_sources)
        real_max = max([max(row["score"], row.get("expert_score", 0)) for row in real_sources] or [0])
        bridge_max = 0.75 if bridge_sources else 0
        result.append({
            "lo_code": lo.lo_code,
            "lo_text": lo.lo_text,
            "real_course_count": len(real_sources),
            "bridge_count": len(bridge_sources),
            "real_max": round(real_max, 4),
            "bridge_max": round(bridge_max, 4),
            "coverage": round(max(real_max, bridge_max), 4),
            "coverage_kind": (
                "goso_regulatory_mapping" if regulatory_evidence
                else "measured_course_match" if real_max >= 0.6
                else "bridge_target_assumption" if bridge_sources
                else "insufficient_evidence"
            ),
            "coverage_explanation": (
                "100% — нормативная связь обязательной дисциплины с результатом ГОСО РК."
                if regulatory_evidence else
                "Процент рассчитан по подтверждённым связям реальных дисциплин с РО."
                if real_max >= 0.6 else
                "75% — служебная оценка проектного bridge-модуля, а не экспертно измеренная связь ЕПВО."
                if bridge_sources else
                "Недостаточно подтверждённых дисциплин или bridge-модулей для этого РО."
            ),
            "status": "real_confirmed" if real_max >= 0.6 else "bridge_supported" if bridge_sources else "weak",
            "real_sources": real_sources[:5],
            "bridge_sources": bridge_sources[:5],
        })
    return {
        "project_version_id": project_version_id,
        "plan_id": plan.id,
        "variant": plan.variant_type,
        "summary": {
            "los": len(result),
            "real_confirmed": sum(1 for row in result if row["status"] == "real_confirmed"),
            "bridge_supported": sum(1 for row in result if row["status"] == "bridge_supported"),
            "weak": sum(1 for row in result if row["status"] == "weak"),
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "items": result,
    }

@router.get("/{project_version_id}/evaluation")
async def get_evaluation(project_version_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.plan import Plan
    from app.planner.plan_metrics import persisted_metrics_current
    plans = db.query(Plan).filter(Plan.project_version_id == project_version_id).order_by(Plan.id.desc()).all()
    latest = {}
    for plan in plans:
        metrics = plan.metrics_json or {}
        latest.setdefault(plan.variant_type, {
            "plan_id": plan.id,
            "variant_type": plan.variant_type,
            "metrics": metrics,
            "metrics_current": persisted_metrics_current(metrics),
        })
    return {"project_version_id": project_version_id, "variants": list(latest.values())}
