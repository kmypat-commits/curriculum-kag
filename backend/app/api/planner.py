from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Body
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from fastapi.responses import StreamingResponse
from io import BytesIO
from datetime import datetime, timezone
import time
from app.database import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.planner.scheduler import build_curriculum_plan, calculate_plan_metrics, _course_curriculum_role, _complexity_min_semester
from app.models.course import Course
from app.models.bridge_module import BridgeModule
from app.models.embedding import MatchFeedback, MatchScore
from app.models.project import ProjectVersion
from app.models.audit import AuditEvent
from app.models.course import CourseChunk
from app.models.epvo import EpvoDisciplineLoLink, EpvoDisciplineNormalized
from app.models.syllabus import SyllabusDraft
from app.services.content_localization import course_localization_map, course_localization_payload, course_translations, course_translation_status
from app.services.epvo_repository import epvo_row_matches_education_level
from app.kag.bridge_generator import call_llm
from app.config import settings
from app.planner.goso import GOSO_COURSE_LO_CODES

router = APIRouter()
_plan_build_status = {}
REPLACEMENT_PREVIEW_CANDIDATE_LIMIT = 1500
REPLACEMENT_PREVIEW_MATCH_LIMIT = 3000

GOSO_DISPLAY_TITLES = {
    "HISTORY_KZ": "История Казахстана",
    "PHILOSOPHY": "Философия",
    "KZ_RU_1": "Казахский (русский) язык 1",
    "KZ_RU_2": "Казахский (русский) язык 2",
    "FOREIGN_1": "Иностранный язык 1",
    "FOREIGN_2": "Иностранный язык 2",
    "ICT": "Информационно-коммуникационные технологии",
    "SOCIAL_POLITICAL": "Модуль социально-политических знаний",
    "PHYSICAL_1": "Физическая культура 1",
    "PHYSICAL_2": "Физическая культура 2",
    "OOD_UNIVERSITY": "Основы права и академической добропорядочности",
    "PROFESSIONAL_PRACTICE": "Профессиональная практика",
    "BACHELOR_FINAL_ATTESTATION": "Написание и защита дипломной работы (проекта) или комплексный экзамен",
    "HISTORY_PHIL_SCIENCE": "История и философия науки",
    "PROF_FOREIGN": "Профессиональный иностранный язык",
    "HIGHER_PEDAGOGY": "Педагогика высшей школы",
    "MANAGEMENT_PSYCHOLOGY": "Психология управления",
    "PEDAGOGICAL_PRACTICE": "Педагогическая практика",
    "RESEARCH_PRACTICE": "Исследовательская практика",
    "NIRM_1": "Научно-исследовательская работа магистранта 1",
    "NIRM_2": "Научно-исследовательская работа магистранта 2",
    "NIRM_3": "Научно-исследовательская работа магистранта 3",
    "NIRM_4": "Научно-исследовательская работа магистранта 4",
    "FINAL_ATTESTATION": "Оформление и защита магистерской диссертации",
    "MASTER_PRODUCTION_PRACTICE": "Производственная практика магистранта",
    "EIRM_PROFILE_60": "Экспериментально-исследовательская работа магистранта",
    "EIRM_PROFILE_90": "Экспериментально-исследовательская работа магистранта",
    "MASTER_PROJECT_FINAL": "Оформление и защита магистерского проекта",
    "DOCTORAL_PEDAGOGICAL_PRACTICE": "Педагогическая практика докторанта",
    "DOCTORAL_RESEARCH_PRACTICE": "Исследовательская практика докторанта",
    "DOCTORAL_PRODUCTION_PRACTICE": "Производственная практика докторанта",
    "NIRD_1": "Научно-исследовательская работа докторанта 1",
    "NIRD_2": "Научно-исследовательская работа докторанта 2",
    "NIRD_3": "Научно-исследовательская работа докторанта 3",
    "NIRD_4": "Научно-исследовательская работа докторанта 4",
    "NIRD_5": "Научно-исследовательская работа докторанта 5",
    "NIRD_6": "Научно-исследовательская работа докторанта, стажировка и завершение диссертации",
    "EIRD_1": "Экспериментально-исследовательская работа докторанта 1",
    "EIRD_2": "Экспериментально-исследовательская работа докторанта 2",
    "EIRD_3": "Экспериментально-исследовательская работа докторанта 3",
    "EIRD_4": "Экспериментально-исследовательская работа докторанта 4",
    "EIRD_5": "Экспериментально-исследовательская работа докторанта 5",
    "EIRD_6": "Экспериментально-исследовательская работа докторанта, стажировка и завершение диссертации",
    "DOCTORAL_FINAL_ATTESTATION": "Написание и защита докторской диссертации",
}


def _goso_definition_code(course: Course | None) -> str:
    code = str(getattr(course, "course_id", "") or "")
    return code.removeprefix("GOSO-KZ-") if code.startswith("GOSO-KZ-") else ""


def _course_display_title(course: Course | None, fallback: str = "Неизвестная дисциплина") -> str:
    definition_code = _goso_definition_code(course)
    return GOSO_DISPLAY_TITLES.get(definition_code) or getattr(course, "title", None) or fallback


def _set_build_status(project_version_id: int, **payload):
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _plan_build_status.setdefault(project_version_id, {}).update(payload)


def _title_key(title: str | None) -> str:
    import re
    import unicodedata
    value = unicodedata.normalize("NFKC", title or "").casefold()
    return " ".join(re.findall(r"\w+", value, flags=re.UNICODE))


def _compact_lo_label(target_los: list[str]) -> str:
    target_los = [code for code in target_los if not str(code or "").startswith("LO-GOSO-")]
    if not target_los:
        return "междисциплинарных результатов"
    if len(target_los) <= 2:
        return ", ".join(target_los)
    return ", ".join(target_los[:2]) + f" и ещё {len(target_los) - 2}"


def _bridge_candidate_fallbacks(version: ProjectVersion, bridge: BridgeModule, target_los: list[str], semester: int) -> list[str]:
    domain1 = version.project.domain1 or "область 1"
    domain2 = version.project.domain2 or "область 2"
    professional_los = [code for code in target_los if not str(code or "").startswith("LO-GOSO-")]
    lo_label = _compact_lo_label(target_los)
    bridge_key = _title_key(bridge.title)
    bridge_text = " ".join(str(value or "") for value in (bridge.title, bridge.description, bridge.goal)).lower()
    if "данн" in bridge_key or "data" in bridge_key:
        focus = "данных и аналитических процессов"
    elif "интеграц" in bridge_key or "integration" in bridge_key:
        focus = "интеграции решений"
    elif "основ" in bridge_key or "foundation" in bridge_key:
        focus = "профессиональных основ"
    elif "практик" in bridge_key or "project" in bridge_key:
        focus = "проектной практики"
    else:
        focus = f"компетенций {lo_label}"
    if professional_los:
        focus = " и ".join(f"компетенции {code}" for code in professional_los[:2])
    if any(marker in bridge_text for marker in ("медицин", "клинич", "пациент", "здоров")):
        themes = ["Клинические данные и процессы", "Основы медицинской информатики", "Цифровые технологии в здравоохранении"]
    elif any(marker in bridge_text for marker in ("агро", "сельск", "растен", "почв", "урож")):
        themes = ["Цифровая агрономия", "Аналитика агропромышленных данных", "Интеллектуальные технологии в АПК"]
    elif any(marker in bridge_text for marker in ("киберслед", "кримин", "forensic", "расслед", "цифровых доказ")):
        themes = ["Цифровая криминалистика", "Правовые основы цифровых расследований", "Анализ цифровых доказательств"]
    elif any(marker in bridge_text for marker in ("робот", "мехатрон", "кинемат")):
        themes = ["Основы робототехнических систем", "Моделирование и управление роботами", "Интеллектуальная мехатроника"]
    elif any(marker in bridge_text for marker in ("ии", "ai", "модель", "алгоритм")):
        themes = ["Прикладной искусственный интеллект", "Аудит и качество ИИ-систем", "Управление данными и моделями"]
    else:
        themes = [
            f"Прикладной анализ области {domain2}",
            f"Профессиональный практикум {domain1} и {domain2}",
            f"Проектирование решений для {domain2}",
        ]
    semester_label = f"семестр {semester}"
    return [
        f"{themes[0]}: {lo_label}",
        f"{themes[1]} для программы «{version.project.title}»",
        f"{themes[2]} ({semester_label}; {focus})",
    ]


def _academic_classification(
    course: Course | None,
    semester: int,
    total_semesters: int,
    role: str,
    jurisdiction: str = "INTERNATIONAL",
) -> dict:
    """Return separate RK curriculum cycle and component labels."""
    raw = str(getattr(course, "cycle_component", None) or "").casefold()
    code = str(getattr(course, "course_id", None) or "")
    if "_ood_" in raw or raw.startswith("goso_ood"):
        cycle, cycle_source = "ООД", "goso"
    elif "_bd_" in raw or raw.startswith("goso_bd"):
        cycle, cycle_source = "БД", "goso"
    elif "_pd_" in raw or raw.startswith("goso_pd"):
        cycle, cycle_source = "ПД", "goso"
    elif raw.startswith("goso_research") or raw.startswith("goso_final"):
        cycle, cycle_source = "ПД", "goso"
    elif role == "general":
        cycle, cycle_source = "ООД", "inferred"
    elif int(semester or 1) <= max(2, int(total_semesters or 8) // 2):
        cycle, cycle_source = "БД", "inferred"
    else:
        cycle, cycle_source = "ПД", "inferred"

    if "elective" in raw or "по выбору" in raw:
        component = "компонент по выбору"
    elif "university" in raw or "вузов" in raw:
        component = "вузовский компонент"
    elif "practice" in raw:
        component = "практика"
    elif "research" in raw:
        component = "научно-исследовательская работа"
    elif "final" in raw:
        component = "итоговая аттестация"
    else:
        component = "обязательный компонент"
    return {
        "academic_cycle": cycle,
        "academic_cycle_source": cycle_source,
        "academic_component": component,
        "protected_by_goso": (
            str(jurisdiction or "INTERNATIONAL").upper() == "KZ"
            and code.startswith("GOSO-KZ-")
        ),
    }


def _plan_snapshot(plan, db: Session) -> dict | None:
    if not plan:
        return None
    from app.models.plan import PlanItem
    items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
    course_ids = [item.course_id for item in items if item.course_id]
    bridge_ids = [item.bridge_module_id for item in items if item.bridge_module_id]
    courses = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()
    }
    bridges = {
        bridge.id: bridge
        for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids or [-1])).all()
    }
    titles = []
    for item in items:
        if item.course_id and item.course_id in courses:
            titles.append(courses[item.course_id].title)
        elif item.bridge_module_id and item.bridge_module_id in bridges:
            titles.append(bridges[item.bridge_module_id].title)
    metrics = plan.metrics_json or {}
    verification = metrics.get("verification") or {}
    return {
        "plan_id": plan.id,
        "variant": plan.variant_type,
        "credits": sum(int(item.credits or 0) for item in items),
        "items": len(items),
        "bridges": len(bridge_ids),
        "min_lo": verification.get("min_lo_coverage"),
        "avg_lo": verification.get("average_lo_coverage"),
        "quality": verification.get("quality_passed"),
        "hard": verification.get("hard_violation_count"),
        "titles": sorted({_title_key(title) for title in titles if title}),
    }


def _build_change_report(old_snapshot: dict | None, new_snapshot: dict | None) -> dict:
    if not old_snapshot or not new_snapshot:
        return {"available": False, "reason": "Нет старого или нового активного плана для сравнения"}
    old_titles = set(old_snapshot.get("titles") or [])
    new_titles = set(new_snapshot.get("titles") or [])
    added = sorted(new_titles - old_titles)
    removed = sorted(old_titles - new_titles)
    return {
        "available": True,
        "old_plan_id": old_snapshot["plan_id"],
        "new_plan_id": new_snapshot["plan_id"],
        "variant": new_snapshot["variant"],
        "credits_delta": int(new_snapshot["credits"] or 0) - int(old_snapshot["credits"] or 0),
        "items_delta": int(new_snapshot["items"] or 0) - int(old_snapshot["items"] or 0),
        "bridges_delta": int(new_snapshot["bridges"] or 0) - int(old_snapshot["bridges"] or 0),
        "min_lo_delta": (
            None if old_snapshot.get("min_lo") is None or new_snapshot.get("min_lo") is None
            else round(float(new_snapshot["min_lo"]) - float(old_snapshot["min_lo"]), 4)
        ),
        "quality_before": old_snapshot.get("quality"),
        "quality_after": new_snapshot.get("quality"),
        "hard_before": old_snapshot.get("hard"),
        "hard_after": new_snapshot.get("hard"),
        "added_count": len(added),
        "removed_count": len(removed),
        "added_titles_sample": added[:12],
        "removed_titles_sample": removed[:12],
    }


@router.get("/version/{project_version_id}/graph")
async def get_plan_graph(
    project_version_id: int,
    variant: str | None = None,
    include_semantic: bool = Query(False, description="Включить тяжёлый семантический слой связей"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the selected curriculum as an explainable prerequisite DAG."""
    from app.models.plan import Plan, PlanItem

    query = db.query(Plan).filter(Plan.project_version_id == project_version_id)
    if variant:
        query = query.filter(Plan.variant_type == variant.upper())
    plan = query.order_by(Plan.is_active.desc(), Plan.id.desc()).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Сначала сформируйте варианты учебного плана")
    version = plan.project_version
    constraints = version.project.constraints_json or {}
    primary_group = str(constraints.get("group_code") or "")
    primary_direction = str(constraints.get("direction_code") or "")
    secondary_group = str(constraints.get("secondary_group_code") or "")
    secondary_direction = str(constraints.get("secondary_direction_code") or "")
    domain_quota = {
        (version.project.domain1 or "").lower().strip(): int(constraints.get("min_domain1_percent") or 0),
        (version.project.domain2 or "").lower().strip(): int(constraints.get("min_domain2_percent") or 0),
    }

    items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
    item_by_course_id = {item.course_id: item for item in items if item.course_id is not None}
    course_ids_in_plan = {item.course_id for item in items if item.course_id is not None}
    postrequisites = {course_id: [] for course_id in course_ids_in_plan}
    for item in items:
        for prerequisite_id in item.prerequisites_snapshot or []:
            if prerequisite_id in postrequisites and item.course_id is not None:
                postrequisites[prerequisite_id].append(item.course_id)

    # Load graph entities and evidence in batches.  Previously this endpoint
    # issued several SQL queries per course and per LO, so simply opening the
    # graph could take seconds even while no generation was running.
    related_course_ids = set(course_ids_in_plan)
    for item in items:
        related_course_ids.update(item.prerequisites_snapshot or [])
    course_by_id = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(related_course_ids or {-1})).all()
    }
    localization_by_course = course_localization_map(db, course_by_id.keys())
    bridge_ids_in_plan = {
        int(item.bridge_module_id) for item in items if item.bridge_module_id is not None
    }
    bridge_by_id = {
        bridge.id: bridge
        for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids_in_plan or {-1})).all()
    }
    epvo_ids = set()
    for course in course_by_id.values():
        if str(course.course_id or "").startswith("EPVO-"):
            try:
                epvo_ids.add(int(str(course.course_id).split("-", 1)[1]))
            except ValueError:
                pass
    epvo_by_id = {
        row.id: row
        for row in db.query(EpvoDisciplineNormalized).filter(
            EpvoDisciplineNormalized.id.in_(epvo_ids or {-1})
        ).all()
    }
    match_rows = db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version_id,
        MatchScore.course_id.in_(course_ids_in_plan or {-1}),
        MatchScore.score >= 0.4,
    ).order_by(MatchScore.score.desc(), MatchScore.id.asc()).all()
    matches_by_course = {}
    match_by_pair = {}
    for match in match_rows:
        matches_by_course.setdefault(int(match.course_id), []).append(match)
        match_by_pair.setdefault((int(match.course_id), int(match.lo_id)), match)
    chunk_ids = {int(match.chunk_id) for match in match_rows if match.chunk_id}
    chunk_by_id = {
        chunk.id: chunk
        for chunk in db.query(CourseChunk).filter(CourseChunk.id.in_(chunk_ids or {-1})).all()
    }
    feedback_by_pair = {}
    feedback_rows = db.query(MatchFeedback).filter(
        MatchFeedback.project_version_id == project_version_id,
        MatchFeedback.course_id.in_(course_ids_in_plan or {-1}),
    ).order_by(MatchFeedback.created_at.asc(), MatchFeedback.id.asc()).all()
    for feedback in feedback_rows:
        feedback_by_pair[(int(feedback.course_id), int(feedback.lo_id))] = feedback

    nodes, node_ids = [], set()
    for item in items:
        if item.course_id is not None:
            course = course_by_id.get(item.course_id)
            if not course:
                continue
            node_id = f"course-{course.id}"
            prerequisite_courses = [
                course_by_id[course_id]
                for course_id in (item.prerequisites_snapshot or [])
                if course_id in course_by_id
            ]
            postrequisite_courses = [
                course_by_id[course_id]
                for course_id in postrequisites.get(course.id, [])
                if course_id in course_by_id
            ]
            epvo_scope = None
            if (course.course_id or "").startswith("EPVO-"):
                try:
                    epvo_id = int(course.course_id.split("-", 1)[1])
                except ValueError:
                    epvo_id = None
                row = epvo_by_id.get(epvo_id) if epvo_id else None
                if row:
                    groups = row.group_codes or []
                    directions = row.direction_codes or []
                    epvo_scope = {
                        "discipline_id": row.id,
                        "groups": groups[:8],
                        "directions": directions[:8],
                        "matched_group": primary_group if primary_group in groups else secondary_group if secondary_group in groups else None,
                        "matched_direction": primary_direction if primary_direction in directions else secondary_direction if secondary_direction in directions else None,
                        "typical_semester": row.typical_semester,
                        "typical_credits": row.typical_credits,
                        "source_program_count": len(row.source_programs or []),
                    }
            nodes.append({
                "id": node_id, "entity_id": course.id, "kind": "course",
                "code": course.course_id, "title": course.title,
                "title_translations": localization_by_course.get(course.id, {}).get("title_translations", {}),
                "description_translations": localization_by_course.get(course.id, {}).get("description_translations", {}),
                "translation_status": localization_by_course.get(course.id, {}).get("translation_status"),
                "semester": item.semester, "credits": item.credits,
                "domain": course.domain, "component": item.course_type,
                "description": course.description,
                "learning_outcomes": course.learning_outcomes or [],
                "topics": course.topics or [],
                "assessment_methods": course.assessment_methods or [],
                "prerequisite_codes": [f"{pre.course_id}: {pre.title}" for pre in prerequisite_courses],
                "postrequisite_codes": [f"{post.course_id}: {post.title}" for post in postrequisite_courses],
                "recommended_semester": course.recommended_semester,
                "epvo_scope": epvo_scope,
                "curriculum_role": (
                    "foundation" if item.semester <= 2 and not item.prerequisites_snapshot
                    else "integrator" if postrequisites.get(course.id)
                    else "specialization"
                ),
            })
        else:
            bridge = bridge_by_id.get(item.bridge_module_id)
            if not bridge:
                continue
            node_id = f"bridge-{bridge.id}"
            nodes.append({
                "id": node_id, "entity_id": bridge.id, "kind": "bridge",
                "code": bridge.course_id, "title": bridge.title,
                "semester": item.semester, "credits": item.credits,
                "domain": "interdisciplinary", "component": item.course_type,
                "description": bridge.description,
                "learning_outcomes": bridge.learning_outcomes or [],
                "topics": bridge.topics or [],
                "assessment_methods": bridge.assessment_methods or [],
            })
        node_ids.add(node_id)

    edges = []
    adjacency = {node_id: [] for node_id in node_ids}
    course_to_node = {node["entity_id"]: node["id"] for node in nodes if node["kind"] == "course"}
    for item in items:
        target = course_to_node.get(item.course_id)
        if not target:
            continue
        for prerequisite_id in item.prerequisites_snapshot or []:
            source = course_to_node.get(prerequisite_id)
            if not source:
                continue
            edges.append({"id": f"{source}-{target}", "source": source, "target": target, "relation": "prerequisite"})
            adjacency[source].append(target)

    # Add deeper evidence-based competency flow without pretending that these
    # are formal prerequisites.  Two courses are connected when an earlier
    # course and a later course both provide strong evidence for the same
    # programme LO.  Limit incoming support edges to keep the graph readable.
    lo_by_node = {node["id"]: {} for node in nodes}
    lo_codes = {lo.id: lo.lo_code for lo in version.learning_outcomes}
    lo_texts = {lo.id: lo.lo_text for lo in version.learning_outcomes}
    for node in nodes:
        if node["kind"] == "course":
            rows = matches_by_course.get(int(node["entity_id"]), [])
            for row in rows:
                code = lo_codes.get(row.lo_id)
                if code:
                    lo_by_node[node["id"]][code] = max(
                        lo_by_node[node["id"]].get(code, 0.0),
                        float(row.score),
                    )
        else:
            bridge = bridge_by_id.get(node["entity_id"])
            for code in (bridge.target_los or []) if bridge else []:
                lo_by_node[node["id"]][code] = 0.75

    for node in nodes:
        evidence = lo_by_node.get(node["id"], {})
        code_to_id = {value: key for key, value in lo_codes.items()}
        lo_details = []
        for code, score in sorted(evidence.items(), key=lambda item: item[1], reverse=True):
            lo_id = code_to_id.get(code)
            detail = {
                "lo_id": lo_id,
                "lo_code": code,
                "lo_text": lo_texts.get(lo_id, ""),
                "score": round(score, 3),
                "source": "ai_prediction" if node["kind"] == "course" else "bridge_target",
                "evidence": {},
                "expert_feedback": None,
            }
            if node["kind"] == "course" and lo_id:
                pair = (int(node["entity_id"]), int(lo_id))
                match = match_by_pair.get(pair)
                if match:
                    detail["evidence"] = match.evidence_json or {}
                    if (detail["evidence"] or {}).get("epvo_expert_score", 0) > 0:
                        detail["source"] = "epvo_expert"
                    if match.chunk_id:
                        chunk = chunk_by_id.get(match.chunk_id)
                        if chunk:
                            detail["chunk"] = {
                                "type": chunk.chunk_type,
                                "text": (chunk.chunk_text or "")[:260],
                            }
                    feedback = feedback_by_pair.get(pair)
                    if feedback:
                        detail["expert_feedback"] = {
                            "verdict": feedback.verdict,
                            "corrected_score": feedback.corrected_score,
                            "comment": feedback.comment,
                        }
            lo_details.append(detail)
        node["lo_evidence"] = lo_details
        node["selection_reason"] = (
            "Закрывает результаты программы и поддерживает последовательность пререквизитов"
            if evidence else "Включена для кредитного баланса и предметной целостности"
        )
        top_expert = next((item for item in lo_details if item.get("source") == "epvo_expert"), None)
        domain_key = (node.get("domain") or "").lower().strip()
        quota = next((percent for key, percent in domain_quota.items() if key and (key in domain_key or domain_key in key)), 0)
        epvo_scope = node.get("epvo_scope") or {}
        node["why_selected"] = {
            "main_reason": node["selection_reason"],
            "role": node.get("curriculum_role") or ("bridge" if node["kind"] == "bridge" else "course"),
            "semester_reason": f"Размещена в семестре {node['semester']} с учётом пререквизитов, нагрузки и рекомендуемого семестра {node.get('recommended_semester') or 'не указан'}.",
            "domain_reason": f"Домен: {node.get('domain') or 'не указан'}; минимальная квота области: {quota}%.",
            "epvo_reason": (
                f"ЕПВО: группа {epvo_scope.get('matched_group') or '—'}, направление {epvo_scope.get('matched_direction') or '—'}; "
                f"типовой семестр {epvo_scope.get('typical_semester') or '—'}, источников программ {epvo_scope.get('source_program_count') or 0}."
                if epvo_scope else "Не является дисциплиной из нормализованного слоя ЕПВО."
            ),
            "expert_reason": (
                f"Экспертная поддержка ЕПВО для {top_expert.get('lo_code')}: {round((top_expert.get('evidence') or {}).get('epvo_expert_score', 0) * 100)}%."
                if top_expert else "Экспертная поддержка ЕПВО для текущих LO не найдена."
            ),
            "lo_count": len(lo_details),
            "top_lo": lo_details[0] if lo_details else None,
            "prerequisites": node.get("prerequisite_codes", []),
            "postrequisites": node.get("postrequisite_codes", []),
        }

    node_by_id = {node["id"]: node for node in nodes}
    formal_pairs = {(edge["source"], edge["target"]) for edge in edges}
    competency_edges = []
    for target in nodes:
        candidates = []
        target_los = lo_by_node.get(target["id"], {})
        if not target_los:
            continue
        for source in nodes:
            if source["semester"] >= target["semester"]:
                continue
            if (source["id"], target["id"]) in formal_pairs:
                continue
            shared = sorted(set(lo_by_node.get(source["id"], {})) & set(target_los))
            if not shared:
                continue
            confidence = sum(
                min(lo_by_node[source["id"]][code], target_los[code])
                for code in shared
            ) / len(shared)
            semester_distance = target["semester"] - source["semester"]
            candidates.append((len(shared), confidence, -semester_distance, source, shared))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        for _, confidence, _, source, shared in candidates[:2]:
            competency_edges.append({
                "id": f"competency-{source['id']}-{target['id']}",
                "source": source["id"],
                "target": target["id"],
                "relation": "competency_flow",
                "shared_los": shared,
                "confidence": round(confidence, 3),
                "semester_distance": target["semester"] - source["semester"],
            })
    edges.extend(competency_edges)

    semantic_edges = []
    if include_semantic:
        # Fill sparse evidence graphs with a separate semantic-progression layer.
        # This remains explicitly inferred and never participates in prerequisite
        # validation. It answers "which later course develops this material?".
        import numpy as np
        from app.kag.embedding_service import embedding_service
        texts = []
        for node in nodes:
            texts.append(" ".join([
                str(node.get("title") or ""),
                str(node.get("description") or ""),
                " ".join(str(item) for item in node.get("learning_outcomes") or []),
                " ".join(str(item) for item in node.get("topics") or []),
            ]))
        vectors = embedding_service.encode_batch(texts)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        normalized_vectors = vectors / np.maximum(norms, 1e-9)
        node_index = {node["id"]: index for index, node in enumerate(nodes)}
        occupied_pairs = formal_pairs | {
            (edge["source"], edge["target"]) for edge in competency_edges
        }
        for target in nodes:
            target_index = node_index[target["id"]]
            candidates = []
            for source in nodes:
                if source["semester"] >= target["semester"]:
                    continue
                pair = (source["id"], target["id"])
                if pair in occupied_pairs:
                    continue
                score = float(np.dot(
                    normalized_vectors[node_index[source["id"]]],
                    normalized_vectors[target_index],
                ))
                if score < 0.12:
                    continue
                distance = target["semester"] - source["semester"]
                candidates.append((score, -distance, source))
            candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            for score, _, source in candidates[:2]:
                semantic_edges.append({
                    "id": f"semantic-{source['id']}-{target['id']}",
                    "source": source["id"], "target": target["id"],
                    "relation": "semantic_progression",
                    "confidence": round(score, 3),
                    "semester_distance": target["semester"] - source["semester"],
                })
        edges.extend(semantic_edges)

    state, cycle_nodes = {}, set()
    def visit(node_id, path):
        if state.get(node_id) == 1:
            cycle_nodes.update(path[path.index(node_id):] if node_id in path else [node_id])
            return
        if state.get(node_id) == 2:
            return
        state[node_id] = 1
        for child in adjacency.get(node_id, []):
            visit(child, path + [node_id])
        state[node_id] = 2
    for node_id in node_ids:
        visit(node_id, [])

    by_semester = {}
    for node in nodes:
        by_semester.setdefault(str(node["semester"]), {"courses": 0, "credits": 0})
        by_semester[str(node["semester"])]["courses"] += 1
        by_semester[str(node["semester"])]["credits"] += int(node["credits"] or 0)

    return {
        "project_version_id": project_version_id, "plan_id": plan.id,
        "variant_type": plan.variant_type, "is_active": plan.is_active == 1,
        "nodes": nodes, "edges": edges, "cycle_nodes": sorted(cycle_nodes),
        "has_cycles": bool(cycle_nodes), "semester_summary": by_semester,
        "formal_edge_count": len(formal_pairs),
        "competency_edge_count": len(competency_edges),
        "semantic_edge_count": len(semantic_edges),
        "semantic_edges_enabled": include_semantic,
    }


@router.get("/version/{project_version_id}/semester-competencies")
async def get_semester_competencies(
    project_version_id: int,
    variant: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return cumulative, evidence-backed competencies after each semester."""
    from app.models.plan import Plan, PlanItem
    from app.models.project import LearningOutcome

    query = db.query(Plan).filter(Plan.project_version_id == project_version_id)
    if variant:
        query = query.filter(Plan.variant_type == variant.upper())
    plan = query.order_by(Plan.is_active.desc(), Plan.id.desc()).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Сначала сформируйте варианты учебного плана")

    items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).order_by(PlanItem.semester).all()
    program_los = {
        lo.id: lo for lo in db.query(LearningOutcome).filter(
            LearningOutcome.project_version_id == project_version_id
        ).all()
    }
    semesters = []
    cumulative_course_outcomes, cumulative_lo_codes = [], set()
    max_semester = max((item.semester for item in items), default=0)
    for semester in range(1, max_semester + 1):
        semester_items = [item for item in items if item.semester == semester]
        completed_courses, new_course_outcomes = [], []
        new_lo_evidence = {}
        for item in semester_items:
            if item.course_id is not None:
                course = db.query(Course).filter(Course.id == item.course_id).first()
                if not course:
                    continue
                completed_courses.append({"code": course.course_id, "title": course.title, "credits": item.credits})
                for outcome in course.learning_outcomes or []:
                    clean = str(outcome).strip()
                    if clean and clean not in cumulative_course_outcomes and clean not in new_course_outcomes:
                        new_course_outcomes.append(clean)
                matches = db.query(MatchScore).filter(
                    MatchScore.project_version_id == project_version_id,
                    MatchScore.course_id == course.id,
                    MatchScore.score >= 0.4,
                ).all()
                for match in matches:
                    lo = program_los.get(match.lo_id)
                    if lo:
                        evidence = new_lo_evidence.setdefault(lo.lo_code, {
                            "lo_code": lo.lo_code, "lo_text": lo.lo_text,
                            "evidence": [], "max_score": 0.0,
                        })
                        evidence["evidence"].append({"course_code": course.course_id, "course_title": course.title, "score": round(float(match.score), 3)})
                        evidence["max_score"] = max(evidence["max_score"], round(float(match.score), 3))
            else:
                bridge = db.query(BridgeModule).filter(BridgeModule.id == item.bridge_module_id).first()
                if not bridge:
                    continue
                completed_courses.append({"code": bridge.course_id, "title": bridge.title, "credits": item.credits})
                for outcome in bridge.learning_outcomes or []:
                    clean = str(outcome).strip()
                    if clean and clean not in cumulative_course_outcomes and clean not in new_course_outcomes:
                        new_course_outcomes.append(clean)
                for lo in program_los.values():
                    if lo.lo_code in (bridge.target_los or []):
                        evidence = new_lo_evidence.setdefault(lo.lo_code, {
                            "lo_code": lo.lo_code, "lo_text": lo.lo_text,
                            "evidence": [], "max_score": 0.75,
                        })
                        evidence["evidence"].append({"course_code": bridge.course_id, "course_title": bridge.title, "score": 0.75})

        cumulative_course_outcomes.extend(new_course_outcomes)
        cumulative_lo_codes.update(new_lo_evidence)
        semesters.append({
            "semester": semester,
            "credits": sum(int(item.credits or 0) for item in semester_items),
            "completed_courses": completed_courses,
            "new_course_outcomes": new_course_outcomes,
            "program_lo_evidence": sorted(new_lo_evidence.values(), key=lambda item: item["lo_code"]),
            "cumulative_course_outcomes": cumulative_course_outcomes.copy(),
            "cumulative_program_los": sorted(cumulative_lo_codes),
            "next_unlocked_courses": [],
        })

    course_semester = {item.course_id: item.semester for item in items if item.course_id is not None}
    for record in semesters:
        current = record["semester"]
        unlocked = []
        for item in items:
            if item.semester != current + 1 or item.course_id is None:
                continue
            prerequisite_ids = item.prerequisites_snapshot or []
            if all(course_semester.get(pid, current + 1) <= current for pid in prerequisite_ids):
                course = db.query(Course).filter(Course.id == item.course_id).first()
                if course:
                    unlocked.append({"code": course.course_id, "title": course.title})
        record["next_unlocked_courses"] = unlocked

    return {"plan_id": plan.id, "variant_type": plan.variant_type, "semesters": semesters}


@router.post("/version/{project_version_id}/semester-insight")
async def generate_semester_insight(
    project_version_id: int,
    semester: int = Body(..., ge=1, le=20),
    variant: str = Body("A"),
    language: str = Body("ru"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Explain in plain language what a student can do after one semester."""
    import json
    from app.models.plan import Plan, PlanItem

    plan = db.query(Plan).filter(
        Plan.project_version_id == project_version_id,
        Plan.variant_type == variant.upper(),
    ).order_by(Plan.is_active.desc(), Plan.id.desc()).first()
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")
    items = db.query(PlanItem).filter(
        PlanItem.plan_id == plan.id, PlanItem.semester == semester
    ).all()
    if not items:
        raise HTTPException(status_code=404, detail="В выбранном семестре нет дисциплин")
    course_ids = [item.course_id for item in items if item.course_id]
    bridge_ids = [item.bridge_module_id for item in items if item.bridge_module_id]
    courses = {row.id: row for row in db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()}
    bridges = {row.id: row for row in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids or [-1])).all()}
    lo_by_id = {row.id: row for row in plan.project_version.learning_outcomes}
    matches = db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version_id,
        MatchScore.course_id.in_(course_ids or [-1]),
        MatchScore.score >= 0.4,
    ).order_by(MatchScore.score.desc()).all()
    lo_rows = []
    seen_los = set()
    for match in matches:
        lo = lo_by_id.get(match.lo_id)
        if lo and lo.lo_code not in seen_los:
            seen_los.add(lo.lo_code)
            lo_rows.append({"code": lo.lo_code, "text": lo.lo_text, "score": round(float(match.score), 3)})
    course_titles = [courses[item.course_id].title for item in items if item.course_id in courses]
    course_titles.extend(bridges[item.bridge_module_id].title for item in items if item.bridge_module_id in bridges)
    fallback_skills = [row["text"] for row in lo_rows[:4]]
    if not fallback_skills:
        fallback_skills = [
            str(value).strip()
            for course in courses.values()
            for value in (course.learning_outcomes or [])
            if str(value).strip()
        ][:4]
    prompt = f"""Return JSON with keys summary (one short paragraph) and skills (3-5 short items).
Language: {language}. Degree programme: {plan.project_version.project.title}.
Semester: {semester}. Courses: {json.dumps(course_titles, ensure_ascii=False)}.
Evidence-backed programme outcomes: {json.dumps(lo_rows[:8], ensure_ascii=False)}.
Do not invent skills not supported by the courses or outcomes."""
    raw = call_llm(prompt, {
        "domain1": plan.project_version.project.domain1,
        "domain2": plan.project_version.project.domain2,
        "gap_los": [],
    })
    source = "local_evidence"
    summary = (
        f"После {semester}-го семестра студент объединяет знания дисциплин «"
        + "», «".join(course_titles[:4])
        + "» и применяет их для подтверждённых результатов программы."
    )
    skills = fallback_skills
    try:
        parsed = json.loads(raw)
        if isinstance(parsed.get("summary"), str) and isinstance(parsed.get("skills"), list):
            summary = parsed["summary"].strip()
            skills = [str(value).strip() for value in parsed["skills"] if str(value).strip()][:5]
            source = "ai"
    except (TypeError, json.JSONDecodeError):
        pass
    return {
        "plan_id": plan.id,
        "variant": plan.variant_type,
        "semester": semester,
        "summary": summary,
        "skills": skills,
        "evidence_los": lo_rows[:8],
        "source": source,
    }


@router.get("/syllabus/{kind}/{entity_id}")
async def generate_course_syllabus(
    kind: str,
    entity_id: int,
    weeks: int = 15,
    contact_share: float = 0.5,
    mode: str = "academic",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate an auditable syllabus draft whose hours equal credits × 30."""
    if weeks < 10 or weeks > 20:
        raise HTTPException(status_code=400, detail="Количество недель должно быть от 10 до 20")
    if contact_share < 0.2 or contact_share > 0.8:
        raise HTTPException(status_code=400, detail="Доля контактной работы должна быть от 0,2 до 0,8")
    if mode not in {"academic", "practical", "project"}:
        raise HTTPException(status_code=400, detail="Режим должен быть академическим, практическим или проектным")

    if kind == "course":
        entity = db.query(Course).filter(Course.id == entity_id).first()
        if not entity:
            raise HTTPException(status_code=404, detail="Дисциплина не найдена")
        localization = course_localization_payload(db, entity.id)
        title_translations = localization.get("title_translations", {})
        description_translations = localization.get("description_translations", {})
        code = entity.course_id
        title = title_translations.get("ru") or title_translations.get("kk") or title_translations.get("en") or entity.title
        description = description_translations.get("ru") or description_translations.get("kk") or description_translations.get("en") or entity.description
        credits, topics = int(entity.credits or 0), list(entity.topics or [])
        outcomes, assessments = list(entity.learning_outcomes or []), list(entity.assessment_methods or [])
        related_localizations = course_localization_map(db, [item.id for item in list(entity.prerequisites) + list(entity.postrequisites)])
        prerequisites = [{
            "code": item.course_id,
            "title": item.title,
            "title_translations": related_localizations.get(item.id, {}).get("title_translations", {}),
        } for item in entity.prerequisites]
        postrequisites = [{
            "code": item.course_id,
            "title": item.title,
            "title_translations": related_localizations.get(item.id, {}).get("title_translations", {}),
        } for item in entity.postrequisites]
    elif kind == "bridge":
        entity = db.query(BridgeModule).filter(BridgeModule.id == entity_id).first()
        if not entity:
            raise HTTPException(status_code=404, detail="Bridge-модуль не найден")
        code, title, description = entity.course_id, entity.title, entity.description
        credits, topics = int(entity.credits or 0), list(entity.topics or [])
        outcomes, assessments = list(entity.learning_outcomes or []), list(entity.assessment_methods or [])
        prerequisites, postrequisites = [], []
    else:
        raise HTTPException(status_code=400, detail="Тип должен быть дисциплиной или bridge-модулем")

    if credits <= 0:
        raise HTTPException(status_code=400, detail="Количество кредитов дисциплины должно быть положительным")
    if not topics:
        topics = [f"{title}: foundational concepts", f"{title}: methods and tools", f"{title}: applied project"]
    if not outcomes:
        outcomes = [f"Explain core concepts of {title}", f"Apply methods of {title} to a practical task"]
    if not assessments:
        assessments = ["Practical assignments", "Midterm assessment", "Final project or examination"]

    total_hours = credits * 30
    contact_hours = round(total_hours * contact_share)
    independent_hours = total_hours - contact_hours
    lecture_share = {"academic": 0.55, "practical": 0.35, "project": 0.20}[mode]
    lecture_hours = round(contact_hours * lecture_share)
    practical_hours = contact_hours - lecture_hours

    def distribute(total, count):
        base, remainder = divmod(int(total), int(count))
        return [base + (1 if index < remainder else 0) for index in range(count)]

    lectures = distribute(lecture_hours, weeks)
    practicals = distribute(practical_hours, weeks)
    independent = distribute(independent_hours, weeks)
    rows = []
    midpoint = max(2, (weeks + 1) // 2)
    mode_activity = {
        "academic": "Guided analysis and seminar discussion",
        "practical": "Laboratory or applied case exercise",
        "project": "Project workshop and supervised implementation",
    }
    for index in range(weeks):
        week = index + 1
        topic_index = min(len(topics) - 1, int(index * len(topics) / weeks))
        topic = str(topics[topic_index])
        if week == 1:
            phase, activity, evidence = "foundation", "Diagnostic task and guided introduction", "Diagnostic response"
        elif week == midpoint:
            phase, activity, evidence = "midterm", "Integrated midterm task", "Assessed midterm artefact"
        elif week == weeks:
            phase, activity, evidence = "final", "Final synthesis and defence", "Final project or examination evidence"
        elif week >= weeks - 2:
            phase, activity, evidence = "integration", mode_activity[mode], "Integrated draft or project increment"
        else:
            phase, activity = "development", mode_activity[mode]
            evidence = "Laboratory report" if mode == "practical" else "Project increment" if mode == "project" else "Analytical assignment"
        if week == midpoint:
            assessment = assessments[min(1, len(assessments) - 1)]
        elif week == weeks:
            assessment = assessments[-1]
        elif week % 3 == 0:
            assessment = assessments[0]
        else:
            assessment = "Formative feedback"
        rows.append({
            "week": week,
            "phase": phase,
            "topic": topic,
            "lecture_hours": lectures[index],
            "practical_hours": practicals[index],
            "independent_hours": independent[index],
            "total_hours": lectures[index] + practicals[index] + independent[index],
            "learning_outcome": str(outcomes[index % len(outcomes)]),
            "learning_activity": activity,
            "assessment": str(assessment),
            "evidence": evidence,
        })

    mapped_outcomes = {row["learning_outcome"] for row in rows}
    validations = {
        "hours_match": sum(row["total_hours"] for row in rows) == total_hours,
        "all_outcomes_mapped": all(str(outcome) in mapped_outcomes for outcome in outcomes),
        "midterm_present": any(row["phase"] == "midterm" for row in rows),
        "final_assessment_present": any(row["phase"] == "final" for row in rows),
        "evidence_present_every_week": all(bool(row["evidence"]) for row in rows),
    }
    validations["ready_for_expert_review"] = all(validations.values())

    return {
        "kind": kind, "entity_id": entity_id, "code": code, "title": title,
        "title_translations": title_translations if kind == "course" else {},
        "description": description,
        "description_translations": description_translations if kind == "course" else {},
        "credits": credits, "weeks": weeks, "mode": mode,
        "hours_per_credit": 30, "total_hours": total_hours,
        "contact_share": contact_share, "contact_hours": contact_hours,
        "lecture_hours": lecture_hours, "practical_hours": practical_hours,
        "independent_hours": independent_hours, "learning_outcomes": outcomes,
        "assessment_methods": assessments, "prerequisites": prerequisites,
        "postrequisites": postrequisites, "thematic_plan": rows, "validations": validations,
        "assumptions": [
            "One academic credit equals 30 academic hours of total student workload.",
            "The contact/independent split is a configurable institutional template.",
            "The draft requires academic-methodological review before approval.",
        ],
        "hours_check": validations["hours_match"],
    }


@router.get("/syllabus/draft/{kind}/{entity_id}")
async def get_syllabus_draft(kind: str, entity_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    draft = db.query(SyllabusDraft).filter(SyllabusDraft.kind == kind, SyllabusDraft.entity_id == entity_id, SyllabusDraft.created_by == current_user.id).order_by(SyllabusDraft.id.desc()).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Сохранённый черновик силлабуса не найден")
    return {"id": draft.id, "status": draft.status, "updated_at": draft.updated_at, "content": draft.content_json}


@router.post("/syllabus/draft/{kind}/{entity_id}")
async def save_syllabus_draft(kind: str, entity_id: int, payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    content = payload.get("content") if isinstance(payload, dict) else None
    rows = content.get("thematic_plan", []) if isinstance(content, dict) else []
    if not rows:
        raise HTTPException(status_code=400, detail="Тематический план пуст")
    expected = int(content.get("credits", 0)) * int(content.get("hours_per_credit", 30))
    actual = sum(int(row.get("total_hours", 0)) for row in rows)
    if expected <= 0 or actual != expected:
        raise HTTPException(status_code=400, detail=f"Недельная нагрузка {actual} ч. не соответствует требуемой {expected} ч.")
    draft = db.query(SyllabusDraft).filter(SyllabusDraft.kind == kind, SyllabusDraft.entity_id == entity_id, SyllabusDraft.created_by == current_user.id).order_by(SyllabusDraft.id.desc()).first()
    if not draft:
        draft = SyllabusDraft(kind=kind, entity_id=entity_id, created_by=current_user.id)
        db.add(draft)
    draft.weeks = int(content.get("weeks", len(rows)))
    draft.contact_share = float(content.get("contact_share", 0.5))
    draft.mode = str(content.get("mode", "academic"))
    draft.content_json = content
    draft.status = "draft"
    db.add(AuditEvent(user_id=current_user.id, action="save_syllabus_draft", entity_type=kind, entity_id=entity_id, details_json={"weeks": draft.weeks, "mode": draft.mode, "hours": actual}))
    db.commit(); db.refresh(draft)
    return {"id": draft.id, "status": draft.status, "updated_at": draft.updated_at}


@router.post("/syllabus/export-docx")
async def export_syllabus_docx(payload: dict, current_user: User = Depends(get_current_user)):
    from docx import Document
    content = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(content, dict) or not content.get("thematic_plan"):
        raise HTTPException(status_code=400, detail="Содержание силлабуса пусто")
    document = Document()
    document.add_heading("Рабочая программа дисциплины (Syllabus)", 0)
    document.add_heading(str(content.get("title", "Дисциплина")), level=1)
    document.add_paragraph(f"Код: {content.get('code', '')} | Кредиты: {content.get('credits', '')} | Недель: {content.get('weeks', '')} | Всего часов: {content.get('total_hours', '')}")
    document.add_heading("Описание", level=2); document.add_paragraph(str(content.get("description") or "Не заполнено"))
    document.add_heading("Результаты обучения", level=2)
    for outcome in content.get("learning_outcomes", []): document.add_paragraph(str(outcome), style="List Number")
    document.add_heading("Тематический план", level=2)
    table = document.add_table(rows=1, cols=7); table.style = "Table Grid"
    for cell, title in zip(table.rows[0].cells, ["Неделя", "Тема", "Деятельность", "Часы", "LO", "Оценивание", "Доказательство"]): cell.text = title
    for row in content["thematic_plan"]:
        values = [row.get("week"), row.get("topic"), row.get("learning_activity"), row.get("total_hours"), row.get("learning_outcome"), row.get("assessment"), row.get("evidence")]
        for cell, value in zip(table.add_row().cells, values): cell.text = str(value or "")
    document.add_paragraph("Черновик требует проверки и утверждения преподавателем или методистом.")
    output = BytesIO(); document.save(output); output.seek(0)
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": "attachment; filename=course_syllabus.docx"})


@router.get("/{plan_id}/evidence-bundle")
async def get_evidence_bundle(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the exact LO-to-course evidence used by a persisted plan."""
    import hashlib
    import json
    from datetime import datetime, timezone
    from app.models.plan import Plan

    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Учебный план не найден")
    course_ids = sorted({item.course_id for item in plan.items if item.course_id is not None})
    version = plan.project_version
    evidence = []
    for lo in version.learning_outcomes:
        rows = db.query(MatchScore).filter(
            MatchScore.project_version_id == version.id,
            MatchScore.lo_id == lo.id,
            MatchScore.course_id.in_(course_ids or [-1]),
        ).order_by(MatchScore.score.desc(), MatchScore.course_id).all()
        evidence.append({
            "lo_code": lo.lo_code,
            "lo_text": lo.lo_text,
            "matches": [{
                "course_id": row.course_id,
                "chunk_id": row.chunk_id,
                "chunk_text": db.query(CourseChunk.chunk_text).filter(CourseChunk.id == row.chunk_id).scalar() if row.chunk_id else None,
                "score": round(float(row.score), 6),
                "model_name": row.model_name,
                "model_version": row.model_version,
                "evidence": row.evidence_json,
                "graph_path": row.graph_path_json,
            } for row in rows],
        })
    payload = {
        "plan_id": plan.id,
        "project_version_id": version.id,
        "variant_type": plan.variant_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "course_ids": course_ids,
        "verification": (plan.metrics_json or {}).get("verification", {}),
        "evidence": evidence,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    payload["sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


@router.post("/{project_version_id}/apply-quality-improvements")
async def apply_quality_improvements(
    project_version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply safe, auditable fixes required by the quality checklist.

    The endpoint fixes the actual failed checks and records every change.
    """
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Версия проекта не найдена")

    from app.models.plan import Plan, PlanItem
    from app.planner.international_quality import evaluate_international_quality, project_course_relevance

    project = version.project
    plan = db.query(Plan).filter(
        Plan.project_version_id == project_version_id,
        Plan.is_active == 1,
    ).order_by(Plan.created_at.desc(), Plan.id.desc()).first()
    if not plan:
        plan = db.query(Plan).filter(Plan.project_version_id == project_version_id).order_by(Plan.created_at.desc(), Plan.id.desc()).first()
    plan_course_ids = {
        int(row.course_id) for row in db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
        if row.course_id
    } if plan else set()
    plan_courses = db.query(Course).filter(Course.id.in_(plan_course_ids or {-1})).all()
    relevance = project_course_relevance(version, plan_courses, db)

    updated_courses = 0
    for course in plan_courses:
        if course.id in relevance["relevant_ids"] and not course.assessment_methods:
            course.assessment_methods = [
                "Практические задания (30%)",
                "Анализ кейса (30%)",
                "Итоговый проект или экзамен (40%)",
            ]
            updated_courses += 1

    constraints = dict(project.constraints_json or {})
    old_excluded = {
        int(value) for value in (constraints.get("excluded_course_ids") or [])
        if str(value).isdigit()
    }
    replaceable_unsupported = set(relevance.get("replaceable_unsupported_ids") or relevance["unsupported_ids"])
    protected_regulatory = set(relevance.get("regulatory_ids") or set())
    newly_excluded = replaceable_unsupported - old_excluded
    constraints["excluded_course_ids"] = sorted(old_excluded | replaceable_unsupported)
    project.constraints_json = constraints

    bridge_code = f"QUALITY_BRIDGE_{project_version_id}"
    bridge = db.query(BridgeModule).filter(BridgeModule.course_id == bridge_code).first()
    interdisciplinary = (
        str(constraints.get("program_type") or "standard").lower() in {"interdisciplinary", "joint"}
        and bool((project.domain2 or "").strip())
    )
    bridge_created = bridge is None and interdisciplinary
    if bridge_created:
        lo_codes = [lo.lo_code for lo in version.learning_outcomes]
        bridge = BridgeModule(
            project_version_id=project_version_id,
            course_id=bridge_code,
            title=f"Интеграционный проект: {project.domain1} и {project.domain2}",
            goal="Связать две предметные области программы в одном прикладном проекте.",
            description="Междисциплинарный модуль, созданный по международному чек-листу качества.",
            credits=5,
            recommended_semester=max(1, int((project.constraints_json or {}).get("total_semesters", 8)) - 1),
            learning_outcomes=[f"Интегрировать знания областей {project.domain1} и {project.domain2}"],
            topics=["Постановка междисциплинарной задачи", "Проектирование решения", "Этика и риски", "Защита проекта"],
            prerequisites=[],
            assessment_methods=["Проект (60%)", "Защита и рефлексия (40%)"],
            source_chunks_json=[],
            generation_params_json={"source": "international_quality_bulk_improvement", "deterministic": True},
            target_los=lo_codes,
            created_by=current_user.id,
        )
        db.add(bridge)
        db.flush()

    existing_verification = ((plan.metrics_json or {}).get("verification") if plan else {}) or {}
    has_hard_plan_violations = bool(
        (existing_verification.get("hard_violation_count") or 0) > 0
        or existing_verification.get("prerequisite_violations")
        or existing_verification.get("semester_load_violations")
        or existing_verification.get("credit_violations")
        or existing_verification.get("domain_quota_violations")
    )
    requires_rebuild = bool(newly_excluded or bridge_created or has_hard_plan_violations)
    metrics_refreshed = False
    if plan and not requires_rebuild:
        plan_items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
        schedule = {}
        for item in plan_items:
            schedule.setdefault(int(item.semester or 1), []).append({
                "course_id": item.course_id,
                "bridge_module_id": item.bridge_module_id,
                "credits": int(item.credits or 0),
            })
        metrics = dict(plan.metrics_json or {})
        verification = metrics.get("verification") or {}
        if verification:
            metrics["international_quality"] = evaluate_international_quality(schedule, version, db, verification)
            plan.metrics_json = metrics
            metrics_refreshed = True

    db.add(AuditEvent(
        user_id=current_user.id,
        action="apply_international_quality_improvements",
        entity_type="project_version",
        entity_id=project_version_id,
        details_json={
            "assessment_courses_updated": updated_courses,
            "bridge_created": bridge_created,
            "bridge_module_id": bridge.id if bridge else None,
            "excluded_irrelevant_course_ids": sorted(newly_excluded),
            "protected_regulatory_course_ids": sorted(protected_regulatory),
            "hard_plan_violations_detected": has_hard_plan_violations,
            "requires_rebuild": requires_rebuild,
            "metrics_refreshed": metrics_refreshed,
        },
    ))
    db.commit()
    return {
        "assessment_courses_updated": updated_courses,
        "bridge_created": bridge_created,
        "bridge_module_id": bridge.id if bridge else None,
        "excluded_irrelevant_courses": len(newly_excluded),
        "protected_regulatory_courses": len(protected_regulatory),
        "hard_plan_violations_detected": has_hard_plan_violations,
        "still_requires_expert_review": len(replaceable_unsupported) == 0 and bool(relevance["unsupported_ids"]),
        "requires_rebuild": requires_rebuild,
        "metrics_refreshed": metrics_refreshed,
    }


@router.post("/{project_version_id}/build")
def build_plan(
    project_version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Build all three curriculum plan variants"""
    current = _plan_build_status.get(project_version_id, {})
    if current.get("state") == "running":
        raise HTTPException(status_code=409, detail="Построение вариантов уже выполняется")
    build_started = time.perf_counter()
    stage_started = build_started
    timings = {}
    _plan_build_status[project_version_id] = {}
    _set_build_status(
        project_version_id,
        state="running",
        stage="matching",
        progress=5,
        started_at=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=0,
        timings=timings,
    )
    try:
        from app.models.plan import Plan
        from app.kag.scoring import compute_all_matches
        from app.planner.goso import ensure_goso_learning_outcomes
        from app.services.epvo_repository import approve_epvo_candidates
        from app.services.planner_stage_cache import (
            EPVO_CACHE_ACTION, SCORING_CACHE_ACTION, cache_hit,
            epvo_input_signature, remember_cache, scoring_input_signature,
        )
        version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
        if not version:
            raise ValueError("Версия проекта не найдена")
        ensure_goso_learning_outcomes(version, db)
        _set_build_status(project_version_id, stage="epvo_repository", progress=8)
        epvo_signature = epvo_input_signature(version, db)
        epvo_cached = cache_hit(db, version, EPVO_CACHE_ACTION, epvo_signature)
        if epvo_cached:
            epvo_sync = {"created": 0, "linked": 0, "scope": "cached", "cached": True, "translations": {}}
        else:
            epvo_sync = approve_epvo_candidates(version, db)
            epvo_signature = epvo_input_signature(version, db)
            remember_cache(
                db, version, EPVO_CACHE_ACTION, epvo_signature, current_user.id,
                {"created": epvo_sync.get("created", 0), "linked": epvo_sync.get("linked", 0)},
            )
        timings["epvo_repository"] = round(time.perf_counter() - stage_started, 2)
        timings["epvo_repository_cached"] = epvo_cached
        stage_started = time.perf_counter()
        epvo_translations = epvo_sync.pop("translations", {})
        _set_build_status(
            project_version_id, stage="scoring", progress=12,
            elapsed_seconds=round(time.perf_counter() - build_started, 1), timings=dict(timings),
        )
        # Compute matches once before building all variants
        def update_scoring_progress(payload: dict):
            _set_build_status(project_version_id, **payload)
        scoring_signature = scoring_input_signature(version, db)
        scoring_cached = cache_hit(db, version, SCORING_CACHE_ACTION, scoring_signature)
        if not scoring_cached:
            scoring_result = compute_all_matches(project_version_id, db, progress_callback=update_scoring_progress)
            scoring_signature = scoring_input_signature(version, db)
            remember_cache(
                db, version, SCORING_CACHE_ACTION, scoring_signature, current_user.id,
                {"total_matches": scoring_result.get("total_matches", 0), "total_los": scoring_result.get("total_los", 0)},
            )
        timings["scoring"] = round(time.perf_counter() - stage_started, 2)
        timings["scoring_cached"] = scoring_cached
        stage_started = time.perf_counter()
        _set_build_status(
            project_version_id, stage="variants", progress=20,
            elapsed_seconds=round(time.perf_counter() - build_started, 1), timings=dict(timings),
        )

        # Replace previous variants only after all new variants are built
        # successfully. This prevents a mix of stale and partial plans.
        old_plans = db.query(Plan).filter(
            Plan.project_version_id == project_version_id
        ).all()
        active_variant = next(
            (plan.variant_type for plan in old_plans if plan.is_active == 1),
            None,
        )
        old_active_plan = next((plan for plan in old_plans if plan.is_active == 1), None)
        old_active_snapshot = _plan_snapshot(old_active_plan, db)

        variants = {}
        for variant_type in ["A", "B", "C"]:
            variant_started = time.perf_counter()
            _plan_build_status[project_version_id].update(
                stage=f"variant_{variant_type}_start", progress={"A": 25, "B": 50, "C": 75}[variant_type]
            )
            result = build_curriculum_plan(
                project_version_id,
                db,
                variant_type,
                commit=False,
            )
            variants[variant_type] = result
            timings[f"variant_{variant_type}"] = round(time.perf_counter() - variant_started, 2)
            _set_build_status(
                project_version_id,
                stage=f"variant_{variant_type}",
                progress={"A": 40, "B": 65, "C": 85}[variant_type],
                elapsed_seconds=round(time.perf_counter() - build_started, 1),
                timings=dict(timings),
            )

        stage_started = time.perf_counter()
        _set_build_status(
            project_version_id, stage="saving", progress=92,
            elapsed_seconds=round(time.perf_counter() - build_started, 1), timings=dict(timings),
        )
        for old_plan in old_plans:
            db.delete(old_plan)

        def _variant_quality_key(item):
            variant_name, row = item
            metrics = row.get("metrics") or {}
            verification = metrics.get("verification") or {}
            quality = metrics.get("international_quality") or {}
            return (
                1 if verification.get("feasible") else 0,
                -int(verification.get("hard_violation_count") or 0),
                float(quality.get("score") or 0.0),
                float(metrics.get("lo_coverage_percentage") or 0.0),
                -int(metrics.get("num_bridge_modules") or 0),
                1 if active_variant and variant_name == active_variant else 0,
            )

        best_variant = max(variants.items(), key=_variant_quality_key)[0] if variants else active_variant
        new_active_plan = db.query(Plan).filter(
            Plan.id == variants[best_variant]["plan_id"]
        ).first() if best_variant and best_variant in variants else None
        if new_active_plan:
            new_active_plan.is_active = 1

        new_active_snapshot = _plan_snapshot(new_active_plan, db)
        change_report = _build_change_report(old_active_snapshot, new_active_snapshot)

        db.commit()
        if epvo_translations:
            try:
                from app.services.content_localization import register_course_translations
                register_course_translations(epvo_translations)
            except OSError:
                pass
        timings["saving"] = round(time.perf_counter() - stage_started, 2)
        _plan_build_status[project_version_id] = {
            "state": "complete",
            "stage": "complete",
            "progress": 100,
            "change_report": change_report,
            "active_variant": best_variant,
            "elapsed_seconds": round(time.perf_counter() - build_started, 1),
            "timings": timings,
        }
        
        return {
            "variants": variants,
            "active_variant": best_variant,
            "epvo_repository": epvo_sync,
            "change_report": change_report,
            "descriptions": {
                "A": "Максимальное покрытие результатов обучения",
                "B": "Минимум новых дисциплин",
                "C": "Минимум конфликтов"
            }
        }
    except Exception as e:
        db.rollback()
        _plan_build_status[project_version_id] = {
            "state": "failed", "stage": "failed", "progress": 0, "error": str(e),
            "elapsed_seconds": round(time.perf_counter() - build_started, 1),
            "timings": timings,
        }
        import traceback
        print(f"PLAN BUILD ERROR: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Не удалось сформировать учебный план: {str(e)}")


@router.get("/{project_version_id}/build-status")
async def get_build_status(
    project_version_id: int,
    current_user: User = Depends(get_current_user),
):
    status = dict(_plan_build_status.get(
        project_version_id, {"state": "idle", "stage": "idle", "progress": 0}
    ))
    if status.get("state") == "running" and status.get("started_at"):
        try:
            started_at = datetime.fromisoformat(status["started_at"])
            status["elapsed_seconds"] = round(
                (datetime.now(timezone.utc) - started_at).total_seconds(), 1
            )
        except (TypeError, ValueError):
            pass
    return status


@router.post("/{project_version_id}/recompute-matches")
def recompute_matches(
    project_version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recompute discipline-to-LO links after course descriptions/translations change."""
    current = _plan_build_status.get(project_version_id, {})
    if current.get("state") == "running":
        raise HTTPException(status_code=409, detail="Построение или пересчёт уже выполняется")
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Версия проекта не найдена")
    _plan_build_status[project_version_id] = {"state": "running", "stage": "scoring", "progress": 5}
    try:
        from app.kag.scoring import compute_all_matches
        from app.planner.goso import ensure_goso_learning_outcomes
        from app.services.planner_stage_cache import (
            SCORING_CACHE_ACTION, remember_cache, scoring_input_signature,
        )

        ensure_goso_learning_outcomes(version, db)

        def update_scoring_progress(payload: dict):
            _plan_build_status[project_version_id].update(payload)

        result = compute_all_matches(project_version_id, db, progress_callback=update_scoring_progress)
        remember_cache(
            db, version, SCORING_CACHE_ACTION, scoring_input_signature(version, db), current_user.id,
            {"total_matches": result.get("total_matches", 0), "total_los": result.get("total_los", 0)},
        )
        _plan_build_status[project_version_id] = {
            "state": "complete",
            "stage": "complete",
            "progress": 100,
            "matches": result.get("total_matches", 0),
            "total_los": result.get("total_los", 0),
        }
        db.add(AuditEvent(
            user_id=current_user.id,
            action="recompute_course_lo_matches",
            entity_type="project_version",
            entity_id=project_version_id,
            details_json={
                "total_matches": result.get("total_matches", 0),
                "total_los": result.get("total_los", 0),
                "prediction": result.get("prediction", {}),
            },
        ))
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        _plan_build_status[project_version_id] = {
            "state": "failed", "stage": "failed", "progress": 0, "error": str(e)
        }
        raise HTTPException(status_code=500, detail=f"Не удалось пересчитать связи дисциплина–LO: {str(e)}")


@router.get("/{project_version_id}/variants")
async def get_variants(
    project_version_id: int,
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
    all_localizations_by_course = course_localization_map(db, all_course_ids)
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
                why_selected = {
                    "role": role,
                    "max_score": round(max_score, 4),
                    "expert_supported": expert_supported,
                    "top_lo_matches": top_matches,
                    "semester_reason": f"Семестр {item.semester}: учтены рекомендуемый семестр, пререквизиты и нагрузка.",
                    "domain_reason": f"Домен дисциплины: {course_obj.domain if course_obj else 'не указан'}.",
                    "selection_reason": (
                        f"Наиболее сильная связь — {top_matches[0]['lo_code']}: итоговая уверенность {round(top_matches[0]['effective_score'] * 100)}%. Оценки ИИ и ЕПВО относятся к одной паре «дисциплина → результат обучения» и не складываются."
                        if top_matches else "Дисциплина включена для структуры, кредитов или доменной целостности плана."
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
                why_selected = {
                    "role": "bridge",
                    "max_score": 0.75,
                    "expert_supported": True,
                    "top_lo_matches": [
                        {"lo_code": code, "lo_text": lo_by_code.get(code).lo_text if lo_by_code.get(code) else code, "score": 0.75, "effective_score": 0.75, "ai_score": None, "expert_score": None, "source": "bridge_target"}
                        for code in (bm_obj.target_los or [])[:3]
                    ] if bm_obj else [],
                    "semester_reason": f"Семестр {item.semester}: bridge-модуль размещён для закрытия междисциплинарного/кредитного пробела.",
                    "domain_reason": "Bridge-модуль относится к междисциплинарной части плана.",
                    "selection_reason": "Bridge-модуль добавлен системой для усиления связей между областями и результатами обучения.",
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
                    {"ru": title, "kk": title, "en": title}
                    if item.course_id and course_obj and _goso_definition_code(course_obj)
                    else all_localizations_by_course.get(item.course_id, {}).get("title_translations", {})
                    if item.course_id else {}
                ),
                "description": course_obj.description if item.course_id and course_obj else None,
                "description_translations": all_localizations_by_course.get(item.course_id, {}).get("description_translations", {}) if item.course_id else {},
                "translation_status": all_localizations_by_course.get(item.course_id, {}).get("translation_status") if item.course_id else None,
                "credits": item.credits,
                "type": item.course_type,
                # Keep the academic component as metadata. It must never be
                # used in place of the actual discipline title in the UI.
                "cycle_component": (
                    course_obj.cycle_component if item.course_id and course_obj
                    else item.course_type
                ),
                "why_selected": why_selected,
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
            "verification": metrics.get("verification", {}),
            "schedule": schedule,
            "semester_los": semester_los,
            "semester_lo_details": semester_lo_details,
            "domain_breakdown": domain_breakdown,
            "epvo_plan_quality": epvo_plan_quality,
            "suspicious_courses": suspicious_courses,
        })
    
    return result


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
            strong_candidate = (
                model_score >= 0.6
                and float(expert_score or 0) >= 0.5
                and credit_distance <= 2
                and coverage_ratio >= 0.75
            )
            rank = coverage_ratio * 100 + combined_score * 50 + float(expert_score or 0) * 50 - credit_distance * 10
            ranked.append({
                "course_id": course.id,
                "course_code": course.course_id,
                "title": course.title,
                "title_translations": {
                    "ru": (row.title_ru if row else None) or course.title,
                    "kk": (row.title_kk if row else None) or course.title,
                    "en": (row.title_en if row else None) or course.title,
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
                "credit_distance": credit_distance,
                "rank": round(rank, 4),
                "scope": required_scope or "interdisciplinary",
            })
        ranked.sort(key=lambda row: row["rank"], reverse=True)
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
    return {
        "project_version_id": project_version_id,
        "plan_id": plan.id,
        "variant": plan.variant_type,
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
    allowed = {
        candidate["course_id"]
        for row in preview["suggestions"]
        if row["bridge_item_id"] == item.id
        for candidate in row["candidates"]
        if candidate.get("strong_candidate")
    }
    if course.id not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Замена не прошла порог качества: нужны подтверждение ЕПВО, связь с профильными LO и близкий объём кредитов",
        )

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
        "requires_regeneration": True,
        "message": "Дисциплина добавлена в план вместо bridge-модуля. Перестройте варианты для полного пересчёта метрик.",
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
    ranked = []
    required_lo_count = 1 if len(target_lo_ids) <= 1 else 2
    domains = [plan.project_version.project.domain1, plan.project_version.project.domain2]
    current_semester = int(item.semester or 1)
    for course in courses:
        row = relevant_rows_by_course.get(course.id)
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
        recommended_semester = int(row.typical_semester or course.recommended_semester or 1)
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
            "title_translations": {"ru": row.title_ru or course.title, "kk": row.title_kk or row.title_ru or course.title, "en": row.title_en or row.title_ru or course.title},
            "description": course.description or (row.content_json or {}).get("description") or "",
            "credits": int(course.credits),
            "model_score": round(float(data.get("model") or 0), 4),
            "expert_score": round(float(data.get("expert") or 0), 4),
            "covered_lo_count": len(covered_los),
            "covered_los": [lo_by_id[lo_id].lo_code for lo_id in sorted(covered_los) if lo_by_id.get(lo_id)],
            "scope_score": round(scope_fit, 4),
            "recommended_semester": recommended_semester,
            "selection_reason": "Совпадает по уровню, направлению, кредитам, семестру и профессиональным LO",
            "rank": round(rank_score, 4),
        })
    ranked.sort(key=lambda row: (row["rank"], row["expert_score"], row["model_score"]), reverse=True)
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

@router.post("/{plan_id}/toggle-active")
async def toggle_plan_active(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Toggle a plan as active and deactivate others for the same project version"""
    from app.models.plan import Plan
    
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Учебный план не найден")
    verification = (plan.metrics_json or {}).get("verification", {})
    
    # A selected plan is the published/active curriculum for this version.
    # Keep the plan flag and the version status in sync so dashboards do not
    # continue to show "draft" after a user has approved a variant.
    db.query(Plan).filter(Plan.project_version_id == plan.project_version_id).update({"is_active": 0})
    plan.is_active = 1
    plan.project_version.status = "active"
    db.add(AuditEvent(
        user_id=current_user.id,
        action="activate_plan",
        entity_type="plan",
        entity_id=plan.id,
        details_json={
            "project_version_id": plan.project_version_id,
            "variant_type": plan.variant_type,
            "version_status": "active",
            "activated_with_hard_violations": int(verification.get("hard_violation_count") or 0) > 0,
            "verification_feasible": verification.get("feasible"),
        },
    ))
    db.commit()
    
    return {
        "message": "Plan activated and project version published",
        "is_active": True,
        "version_status": "active",
    }

@router.get("/{project_version_id}/evaluation")
async def get_evaluation(project_version_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.plan import Plan
    plans = db.query(Plan).filter(Plan.project_version_id == project_version_id).order_by(Plan.id.desc()).all()
    latest = {}
    for plan in plans:
        latest.setdefault(plan.variant_type, {"plan_id": plan.id, "variant_type": plan.variant_type, "metrics": plan.metrics_json or {}})
    return {"project_version_id": project_version_id, "variants": list(latest.values())}
