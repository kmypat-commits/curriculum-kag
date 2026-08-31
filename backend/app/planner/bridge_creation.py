from __future__ import annotations

from itertools import combinations
import math
import re
from statistics import median
from typing import Dict, List

from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.planner.bridge_policy import bridge_module_limit
from app.models.bridge_module import BridgeModule
from app.models.course import Course, course_prerequisites
from app.models.embedding import MatchScore
from app.models.epvo import (
    EpvoDirection,
    EpvoDisciplineLoLink,
    EpvoDisciplineNormalized,
    EpvoGroup,
)
from app.models.plan import Plan, PlanItem
from app.models.project import LearningOutcome, ProjectVersion
from app.planner.admission import (
    audit_final_course_admission as _audit_final_course_admission,
    credible_professional_lo_by_course as _credible_professional_lo_by_course,
    minimum_appropriate_semester as _minimum_appropriate_semester,
)
from app.planner.course_policy import (
    course_curriculum_role as _course_curriculum_role,
    course_role_rank as _course_role_rank,
    education_level_course_allowed as _education_level_course_allowed,
    project_domain_terms as _project_domain_terms,
)
from app.planner.goso import merge_goso_items
from app.planner.scheduler_catalogue import (
    foundation_equivalent_title_key as _foundation_equivalent_title_key,
    is_component_placeholder_title as _is_component_placeholder_title,
    unique_items_by_title as _unique_items_by_title,
)
from app.planner.scheduler_domain_rules import (
    course_domain_matches as _course_domain_matches,
    has_foreign_professional_title as _has_foreign_professional_title,
    is_interdisciplinary_title_relevant as _is_interdisciplinary_title_relevant,
    is_it_medicine_support_course as _is_it_medicine_support_course,
    invalid_project_domain_label as _is_invalid_project_domain_label,
)
from app.planner.scheduler_text import (
    has_domain_term as _has_domain_term,
    short_lo_theme as _short_lo_theme,
)
from app.planner.scheduler_utils import title_key as _title_key
from app.planner.semester_rules import (
    complexity_min_semester as _complexity_min_semester,
    cycle_min_semester as _cycle_min_semester,
    foundation_max_semester as _foundation_max_semester,
    late_stage_min_semester as _late_stage_min_semester,
    minimum_appropriate_semester as _item_minimum_appropriate_semester,
)
from app.planner.verifier import (
    TOTAL_CREDIT_TOLERANCE,
    _ict_competency_audit,
    _ict_competency_requirements,
    verify_curriculum_plan,
)
from app.services.epvo_repository import (
    epvo_row_matches_education_level,
    epvo_row_relevance_score,
)


def _bridge_item(module: BridgeModule) -> Dict:
    item = {
        "bridge_module_id": module.id,
        "title": module.title,
        "domain": "interdisciplinary",
        "credits": module.credits or 5,
        "recommended_semester": module.recommended_semester,
        "prerequisites": module.prerequisites or [],
        "type": "bridge",
    }
    if (module.course_id or "").startswith(("CORE_BRIDGE_", "SECONDARY_")):
        recommended = int(module.recommended_semester or 1)
        item["latest_semester"] = recommended + (
            2 if (module.course_id or "").startswith("CORE_BRIDGE_") else 1
        )
    return item

def _force_bridge_item(
    items: List[Dict],
    module: BridgeModule | None,
    variant_type: str = "A",
    target_credits: int | None = None,
) -> List[Dict]:
    if module is None or any(item.get("bridge_module_id") == module.id for item in items):
        return items
    normalized = [dict(item) for item in items]
    protected_course_ids = {
        prerequisite_id
        for item in normalized
        for prerequisite_id in (item.get("prerequisites") or [])
    }
    bridge = _bridge_item(module)
    current_total = sum(int(item.get("credits") or 0) for item in normalized)
    gap = (target_credits - current_total) if target_credits is not None else 0
    if target_credits is not None and gap >= 3:
        credits = min(int(module.credits or 5), gap)
        if 0 < gap - credits < 3:
            credits = gap - 3
        if credits >= 3:
            bridge["credits"] = credits
            normalized.append(bridge)
            return normalized
    if (
        target_credits is not None
        and current_total + int(module.credits or 5) <= target_credits
    ):
        normalized.append(bridge)
        return normalized
    same_credit = [
        (index, item) for index, item in enumerate(normalized)
        if item.get("course_id") is not None
        and not item.get("regulatory_required")
        and not item.get("competency_required")
        and not item.get("domain_quota_reserve")
        and item.get("course_id") not in protected_course_ids
        and int(item.get("credits") or 0) == int(module.credits or 5)
    ]
    replaceable = same_credit or [
        (index, item) for index, item in enumerate(normalized)
        if item.get("course_id") is not None
        and not item.get("regulatory_required")
        and not item.get("competency_required")
        and not item.get("domain_quota_reserve")
        and item.get("course_id") not in protected_course_ids
    ]
    if replaceable:
        offset = {"A": 0, "B": 1, "C": 2}.get(variant_type, 0)
        replace_index, replaced = replaceable[offset % len(replaceable)]
        bridge["credits"] = int(replaced.get("credits") or module.credits or 5)
        normalized[replace_index] = bridge
    else:
        normalized.append(bridge)
    return normalized

def _ensure_foundation_capacity(
    selected_courses: List[Dict],
    project_version: ProjectVersion,
    db: Session,
) -> List[Dict]:
    """Replace safe late electives with prerequisite-free foundation modules.

    A curriculum cannot have a balanced first semester when nearly every
    selected course depends on the same small foundation.  The replacement
    preserves total credits and explicitly marks the generated modules for
    semester one.
    """
    constraints = project_version.project.constraints_json or {}
    nominal = int(constraints.get("max_credits_per_semester", 30))
    normalized = [dict(item) for item in selected_courses]
    selected_ids = {item.get("course_id") for item in normalized if item.get("course_id") is not None}
    protected = {
        prerequisite
        for item in normalized
        for prerequisite in (item.get("prerequisites") or [])
        if prerequisite in selected_ids
    }
    foundation_credits = sum(
        int(item.get("credits") or 0)
        for item in normalized
        if item.get("course_id") is not None and not (item.get("prerequisites") or [])
        or item.get("latest_semester") == 1
    )
    deficit = max(0, nominal - foundation_credits)
    target_credits = int(constraints.get("total_credits", 240))
    credit_gap = max(0, target_credits - sum(int(item.get("credits") or 0) for item in normalized))
    existing_bridges = sum(1 for item in normalized if item.get("bridge_module_id") is not None)
    slots = max(0, int(constraints.get("max_new_courses", 5)) - existing_bridges)
    if deficit <= 0 or slots <= 0 or not constraints.get("allow_new_courses", True):
        return normalized

    replacement_needed = max(0, deficit - credit_gap)
    candidates = [
        (index, item)
        for index, item in enumerate(normalized)
        if item.get("course_id") is not None
        and item.get("course_id") not in protected
        and (item.get("prerequisites") or [])
    ]
    # Exact subset-sum keeps the curriculum credit total unchanged.
    choices = {0: []}
    for index, item in candidates:
        credits = int(item.get("credits") or 0)
        for subtotal, indexes in list(choices.items())[::-1]:
            value = subtotal + credits
            if value <= replacement_needed and value not in choices:
                choices[value] = indexes + [index]
    replacement_credits = max(choices)
    module_credits = min(deficit, credit_gap + replacement_credits)
    if module_credits <= 0:
        return normalized
    indexes_to_remove = set(choices[replacement_credits])
    normalized = [item for index, item in enumerate(normalized) if index not in indexes_to_remove]
    desired_count = min(slots, max(1, math.ceil(module_credits / 7)))
    modules = ensure_credit_bridge_modules(
        project_version,
        db,
        module_credits,
        slots,
        desired_count=desired_count,
    )
    added_items = []
    for module in modules:
        item = {
            "bridge_module_id": module.id,
            "title": module.title,
            "domain": "interdisciplinary",
            "credits": module.credits or 5,
            "recommended_semester": 1,
            "latest_semester": 1,
            "prerequisites": [],
            "type": "bridge",
        }
        normalized.append(item)
        added_items.append((module, item))
    shortfall = max(0, target_credits - sum(int(item.get("credits") or 0) for item in normalized))
    for module, item in reversed(added_items):
        if shortfall <= 0:
            break
        room = max(0, 7 - int(item["credits"]))
        increase = min(room, shortfall)
        item["credits"] += increase
        module.credits = item["credits"]
        shortfall -= increase
    return normalized

def _trim_to_target_credits(items: List[Dict], target_credits: int, db: Session) -> List[Dict]:
    """Prefer exact total credits without breaking prerequisite closure."""
    normalized = [dict(item) for item in items]

    def total() -> int:
        return sum(int(item.get("credits") or 0) for item in normalized)

    for item in sorted(
        (item for item in normalized if item.get("bridge_module_id") is not None),
        key=lambda row: int(row.get("credits") or 0),
        reverse=True,
    ):
        excess = total() - target_credits
        if excess <= 0:
            break
        current = int(item.get("credits") or 0)
        reduction = min(excess, max(0, current - 3))
        if reduction <= 0:
            continue
        item["credits"] = current - reduction
        module = db.query(BridgeModule).filter(BridgeModule.id == item["bridge_module_id"]).first()
        if module:
            module.credits = item["credits"]

    # A repository discipline is an atomic approved unit: its typical credit
    # value must not be silently rewritten to make the arithmetic fit.  Only a
    # generated bridge may flex within its explicit 3--7 credit envelope.
    # Real courses are removed/replaced as whole units below.

    while total() > target_credits:
        excess = total() - target_credits
        selected_ids = {item.get("course_id") for item in normalized if item.get("course_id") is not None}
        protected = {
            prerequisite_id
            for item in normalized
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in selected_ids
        }
        removable = [
            (index, item)
            for index, item in enumerate(normalized)
            if item.get("course_id") is not None
            and not item.get("regulatory_required")
            # A competency repair is a deliberate quality constraint, not a
            # low-priority elective.  Never trim it merely to close a credit
            # gap; bridge credits are adjusted before removing core evidence.
            and item.get("selection_method") != "ict_competency_repair"
            and not item.get("competency_required")
            # A quota reserve is selected from the explicitly chosen EPVO
            # direction/group. It may only be replaced by another valid
            # domain-quota repair, never silently trimmed for arithmetic.
            and not item.get("domain_quota_reserve")
            and item.get("course_id") not in protected
            and int(item.get("credits") or 0) <= excess
            and total() - int(item.get("credits") or 0) >= target_credits
        ]
        if not removable:
            break
        removable.sort(key=lambda pair: (
            int(pair[1].get("credits") or 0) != excess,
            int(pair[1].get("recommended_semester") or 99),
            int(pair[1].get("course_id") or 0),
        ))
        del normalized[removable[0][0]]

    return _unique_items_by_title(normalized)

def _fill_existing_bridge_credit_gap(
    items: List[Dict], target_credits: int, db: Session
) -> List[Dict]:
    """Use the explicit 3--7 credit bridge envelope for a residual gap.

    Late prerequisite/domain repairs can remove a real course after the last
    bridge-slot check. Adding another module would violate ``max_new_courses``;
    increasing an existing bridge is the safe atomic repair and keeps the plan
    at its requested total without changing real-course credits.
    """
    normalized = [dict(item) for item in items]
    gap = max(0, int(target_credits) - sum(int(item.get("credits") or 0) for item in normalized))
    for item in reversed(normalized):
        if gap <= 0 or item.get("bridge_module_id") is None:
            continue
        room = max(0, 7 - int(item.get("credits") or 0))
        increase = min(room, gap)
        if increase <= 0:
            continue
        item["credits"] = int(item.get("credits") or 0) + increase
        module = db.query(BridgeModule).filter(BridgeModule.id == item["bridge_module_id"]).first()
        if module:
            module.credits = item["credits"]
        gap -= increase
    return normalized

def ensure_core_interdisciplinary_bridge(project_version: ProjectVersion, db: Session) -> BridgeModule | None:
    """Create one explicit domain-bridge module for interdisciplinary programmes."""
    project = project_version.project
    constraints = project.constraints_json or {}
    program_type = str(constraints.get("program_type") or "").lower()
    domain1, domain2 = (project.domain1 or "").strip(), (project.domain2 or "").strip()
    if program_type not in {"interdisciplinary", "joint"} or not domain1 or not domain2:
        return None
    if _title_key(domain1) == _title_key(domain2):
        return None

    total_semesters = int(constraints.get("total_semesters", 8) or 8)
    code = f"CORE_BRIDGE_{project_version.id}"
    domain1_display = "IT" if _title_key(domain1) in {"it", "айти"} else domain1
    domain2_key = _title_key(domain2)
    domain2_display = "медицина" if any(token in domain2_key for token in ("medicine", "medical", "медицин", "медицина", "health", "clinical", "клиник")) else domain2
    title = f"Интеграционный модуль: {domain1_display} и {domain2_display}"
    target_los = [
        lo.lo_code for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    ]
    module = db.query(BridgeModule).filter(
        BridgeModule.project_version_id == project_version.id,
        BridgeModule.course_id == code,
    ).first()
    payload = {
        "title": title,
        "goal": f"Связать {domain1} и {domain2} в прикладном междисциплинарном проекте.",
        "description": (
            f"Bridge-модуль для программы {project.title}: студенты применяют IT-инструменты, "
            f"данные и цифровые платформы к задачам области {domain2}, учитывая безопасность, "
            "этику, нормативные ограничения и доказательность решений."
        ),
        "credits": 5,
        "recommended_semester": max(2, min(total_semesters - 1, total_semesters // 2)),
        "learning_outcomes": [
            f"Применять цифровые инструменты и данные для решения задач области {domain2}.",
            f"Проектировать междисциплинарное решение на стыке {domain1} и {domain2}.",
            "Оценивать безопасность, этику, качество данных и нормативные ограничения решения.",
        ],
        "topics": [
            f"Проблемное поле {domain2} для IT-решений",
            "Медицинские/профессиональные данные и качество источников",
            "Цифровые платформы, интеграция и безопасность",
            "Этика, приватность и регуляторные ограничения",
            "Командный проект и защита решения",
        ],
        "assessment_methods": ["проект", "case study", "презентация"],
        "target_los": target_los,
    }
    if module is None:
        module = BridgeModule(
            project_version_id=project_version.id,
            course_id=code,
            prerequisites=[],
            source_chunks_json=[],
            generation_params_json={"mode": "core_interdisciplinary_bridge"},
            **payload,
        )
        db.add(module)
    else:
        for key, value in payload.items():
            setattr(module, key, value)
        module.prerequisites = []
        module.generation_params_json = {"mode": "core_interdisciplinary_bridge"}
    db.flush()
    return module

def ensure_secondary_domain_bridge_modules(project_version: ProjectVersion, db: Session) -> List[BridgeModule]:
    """Create visible secondary-domain modules for interdisciplinary curricula."""
    project = project_version.project
    constraints = project.constraints_json or {}
    program_type = str(constraints.get("program_type") or "").lower()
    domain1, domain2 = (project.domain1 or "").strip(), (project.domain2 or "").strip()
    if program_type not in {"interdisciplinary", "joint"} or not domain1 or not domain2:
        return []
    total_semesters = int(constraints.get("total_semesters", 8) or 8)
    secondary = domain2
    secondary_key = _title_key(secondary)
    is_medical = any(token in secondary_key for token in ("medicine", "medical", "медицин", "медицина", "health", "clinical", "клиник"))
    secondary_display = "медицины" if is_medical else secondary
    templates = [
        {
            "suffix": "SECONDARY_FOUNDATION",
            "title": f"Основы {secondary_display} для IT-специалистов" if is_medical else f"Основы области {secondary} для {domain1}",
            "semester": 2,
            "topics": [
                "Профессиональный контекст и терминология",
                "Типовые процессы и участники отрасли",
                "Данные, документы и доказательность",
                "Риски, этика и нормативные ограничения",
            ],
        },
        {
            "suffix": "SECONDARY_DATA",
            "title": "Медицинские данные и клинические процессы" if is_medical else f"Данные и процессы области {secondary}",
            "semester": 3,
            "topics": [
                "Структура профессиональных данных",
                "Качество, полнота и интерпретация данных",
                "Цифровой workflow и интеграция систем",
                "Прикладной кейс междисциплинарного анализа",
            ],
        },
        {
            "suffix": "SECONDARY_ADVANCED",
            "title": "Прикладной проект в области медицины" if is_medical else f"Прикладной проект области {secondary}",
            "semester": max(4, min(total_semesters - 1, 5)),
            "topics": [
                "Постановка междисциплинарной задачи",
                "Интерпретация отраслевых данных",
                "Оценка рисков и ограничений решения",
                "Защита прикладного проекта",
            ],
        },
        {
            "suffix": "SECONDARY_INTEGRATION",
            "title": "Медицинская интероперабельность, клинические данные и цифровая безопасность" if is_medical else f"Интеграция цифровых решений в области {secondary}",
            "semester": max(5, min(total_semesters - 1, 6)),
            "credits": 6,
            "topics": [
                "Стандарты и жизненный цикл предметных данных",
                "Интероперабельность цифровых систем и качество данных",
                "Защита чувствительных данных и управляемые риски",
                "Проверка интеграционного решения на предметном кейсе",
            ],
        },
        {
            "suffix": "SECONDARY_COVERAGE",
            "title": "Практикум предметного домена: клинические данные и процессы" if is_medical else f"Практикум предметного домена: {secondary}",
            "semester": max(3, min(total_semesters - 1, 4)),
            "credits": 3,
            "topics": [
                "Предметные данные и типовые рабочие процессы",
                "Качество и интерпретация отраслевых данных",
                "Прикладной кейс цифрового решения",
            ],
        },
        {
            "suffix": "SECONDARY_APPLICATION",
            "title": "Практическое применение цифровых решений в здравоохранении" if is_medical else f"Практическое применение решений в области {secondary}",
            "semester": max(4, min(total_semesters - 1, 5)),
            "credits": 5,
            "topics": [
                "Отраслевой сценарий и постановка задачи",
                "Валидация цифрового решения на предметных данных",
                "Риски, качество и защита результата",
            ],
        },
    ]
    target_los = [
        lo.lo_code for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    ]
    modules: List[BridgeModule] = []
    for index, template in enumerate(templates, start=1):
        code = f"{template['suffix']}_{project_version.id}"
        module = db.query(BridgeModule).filter(
            BridgeModule.project_version_id == project_version.id,
            BridgeModule.course_id == code,
        ).first()
        payload = {
            "title": template["title"],
            "goal": f"Дать студентам {domain1} предметную базу области {secondary} для корректного проектирования цифровых решений.",
            "description": (
                f"Предметный модуль вторичного домена {secondary}: терминология, процессы, данные, "
                "ограничения и кейсы, необходимые для междисциплинарной образовательной программы."
            ),
            "credits": int(template.get("credits") or (3 if template["suffix"] == "SECONDARY_ADVANCED" else 5)),
            "recommended_semester": max(1, min(total_semesters - 1, int(template["semester"]))),
            "learning_outcomes": [
                f"Объяснять ключевые процессы и понятия области {secondary}.",
                f"Интерпретировать данные области {secondary} для задач {domain1}.",
                "Учитывать этические, правовые и качественные ограничения предметной области.",
            ],
            "topics": template["topics"],
            "assessment_methods": ["case study", "практическое задание", "мини-проект"],
            "target_los": target_los[index - 1::2] or target_los,
        }
        if module is None:
            module = BridgeModule(
                project_version_id=project_version.id,
                course_id=code,
                prerequisites=[],
                source_chunks_json=[],
                generation_params_json={"mode": "secondary_domain_foundation"},
                **payload,
            )
            db.add(module)
        else:
            for key, value in payload.items():
                setattr(module, key, value)
            module.prerequisites = []
            module.generation_params_json = {"mode": "secondary_domain_foundation"}
        modules.append(module)
    db.flush()
    return modules

def ensure_credit_bridge_modules(
    project_version: ProjectVersion,
    db: Session,
    needed_credits: int,
    slots: int,
    desired_count: int | None = None,
) -> List[BridgeModule]:
    """Create deterministic domain-aware bridge modules when constraints leave credit gaps.

    This avoids filling a curriculum with unrelated repository courses simply
    because they have no prerequisites. The modules remain explicit bridge
    candidates and can later be promoted by an expert.
    """
    if needed_credits <= 0 or slots <= 0:
        return []

    project = project_version.project
    # Regulatory ГОСО outcomes are already evidenced by the mandatory
    # components merged into every KZ curriculum.  A synthetic credit-gap
    # module must never claim those outcomes: doing so both overstates its
    # pedagogical role and prevents the final EPVO replacement pass from
    # recognising the bridge as redundant.
    learning_outcomes = [
        lo for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    ]
    lo_codes = [lo.lo_code for lo in learning_outcomes]
    lo_by_code = {lo.lo_code: lo for lo in learning_outcomes}
    base_code = f"AUTO_BRIDGE_{project_version.id}_"
    existing = {
        bm.course_id: bm
        for bm in db.query(BridgeModule).filter(
            BridgeModule.project_version_id == project_version.id,
            BridgeModule.course_id.like(f"{base_code}%"),
        ).all()
    }

    remaining = int(needed_credits)
    modules: List[BridgeModule] = []
    minimum_count = max(1, math.ceil(remaining / 7))
    maximum_count = max(1, min(slots, remaining // 3))
    count = min(maximum_count, max(minimum_count, desired_count or minimum_count))
    for index in range(1, count + 1):
        module_code = f"{base_code}{index}"
        slots_left = count - index + 1
        credits = max(3, min(7, math.ceil(remaining / slots_left)))
        remaining -= credits
        target_los = lo_codes[index - 1::count] or lo_codes
        theme = _short_lo_theme(lo_by_code.get(target_los[0]) if target_los else None)
        domain_pair = (
            f"{project.domain1} и {project.domain2}"
            if project.domain1 and project.domain2 and project.domain1 != project.domain2
            else str(project.domain1 or project.domain2 or "выбранного направления")
        )
        title = f"Интеграционный модуль {theme}: {domain_pair} - семестр {index}"
        goal = f"Закрыть разрыв по {', '.join(target_los[:3]) or 'результатам обучения'} через практическую связь направлений {domain_pair}."
        description = (
            f"Bridge-модуль связывает дисциплины направления {domain_pair} с результатами "
            f"{', '.join(target_los[:4]) or 'обучения программы'}. Используется только когда "
            "в репозитории ЕПВО пока нет достаточно сильной реальной дисциплины."
        )
        bm = existing.get(module_code)
        if bm is None:
            bm = BridgeModule(
                project_version_id=project_version.id,
                course_id=module_code,
                title=title,
                goal=goal,
                description=description,
                credits=credits,
                recommended_semester=min(index, int((project.constraints_json or {}).get("total_semesters", 1))),
                learning_outcomes=[
                    f"Apply {project.domain2} tools to professional tasks in {project.domain1}.",
                    "Evaluate data, platform, legal, ethical, and cybersecurity constraints.",
                    "Design evidence-based digital transformation recommendations.",
                ],
                topics=[
                    "Digital transformation context",
                    "Data-driven public administration",
                    "GovTech platforms and interoperability",
                    "Information security and personal data protection",
                    "AI-supported decision-making",
                    "Implementation roadmap and stakeholder communication",
                ],
                prerequisites=[],
                assessment_methods=["project", "case study", "presentation"],
                source_chunks_json=[],
                generation_params_json={"mode": "deterministic_credit_gap_bridge"},
                target_los=target_los,
            )
            db.add(bm)
        else:
            bm.credits = credits
            bm.title = title
            bm.goal = goal
            bm.description = description
            bm.target_los = target_los
        modules.append(bm)

    db.flush()
    return modules
