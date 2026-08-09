"""Course classification and education-level policies used by the planner.

This module contains cohesive policy decisions and deliberately has no plan
mutation logic.  Keeping them separate makes the rules independently testable
and prevents API or scheduling code from growing another policy copy.
"""

from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.epvo import EpvoDirection, EpvoGroup
from app.models.project import ProjectVersion
from app.planner.scheduler_domain_rules import (
    course_domain_matches,
    invalid_project_domain_label,
    is_interdisciplinary_title_relevant,
)
from app.planner.scheduler_text import has_domain_term
from app.planner.scheduler_utils import title_key


def project_domain_terms(project_version: ProjectVersion, db: Session) -> List[str]:
    """Return normalized human labels and registry codes for project scope."""
    project = project_version.project
    constraints = project.constraints_json or {}
    raw_domains = [project.domain1, project.domain2]
    scope_sources = [
        (constraints.get("group_code"), EpvoGroup),
        (constraints.get("direction_code"), EpvoDirection),
        (constraints.get("secondary_group_code"), EpvoGroup),
        (constraints.get("secondary_direction_code"), EpvoDirection),
    ]
    terms: list[str] = []
    for value in raw_domains:
        if not invalid_project_domain_label(str(value or "")):
            terms.append(str(value or ""))
    for code, model in scope_sources:
        code = str(code or "").strip()
        if not code:
            continue
        row = db.query(model).filter(model.code == code).first()
        if row:
            terms.extend([row.title_ru, row.title_kk, row.title_en, row.code])
        else:
            terms.append(code)

    result: list[str] = []
    seen = set()
    for term in terms:
        value = str(term or "").lower().strip()
        key = title_key(value)
        if key and key not in seen and not invalid_project_domain_label(value):
            seen.add(key)
            result.append(value)
    return result


def course_curriculum_role(course: Course, project_domains: List[str]) -> str:
    """Classify a course as core, general, or outside the project scope."""
    title = title_key(course.title)
    general_title_terms = (
        "основы экономики", "финансовой грамотности", "правовые основы",
        "основы права", "антикорруп", "академическ", "социально политическ",
        "безопасности жизнедеятельности", "устойчивого развития",
        "история медицины", "психология управления", "иностранный язык",
        "foreign language", "введение в профессию", "методология научного исследования",
        "организация и планирование научных исследований",
        "экономика устойчивого развития", "правовые основы бизнеса",
        "педагогика и валеология", "современные проблемы менеджмента",
        "менеджмент программных проектов", "введение в научные исследования",
        "medical interview and basics of medical ethics",
    )
    if ("язык" in title or "language" in title) and not any(
        marker in title for marker in ("программ", "programming", "анализа данных", "data analysis")
    ):
        return "general"
    if any(term in title for term in general_title_terms):
        return "general"
    if not course_domain_matches(course, project_domains):
        return "other"

    domains = " ".join(project_domains).lower()
    has_it = "it" in domains or "информ" in domains or "computer" in domains or "кибер" in domains
    has_forensics = "forensic" in domains or "криминал" in domains or "расслед" in domains
    if has_it and has_forensics:
        text = title_key(" ".join([course.title or "", course.description or ""]))
        cyber_terms = (
            "кибер", "безопас", "защит", "сеть", "сетей", "сервер",
            "forensic", "форензик", "криминалист", "расслед", "доказател",
            "экспертн", "судеб", "процессу", "инцидент", "угроз", "вредонос",
            "malware", "киберпреступ", "атак", "уязвим", "osint", "лог", "журнал",
            "цепочк", "документирован",
        )
        if not has_domain_term(text, cyber_terms):
            return "general"
    return "core" if is_interdisciplinary_title_relevant(course, project_domains) else "general"


def course_role_rank(course: Course | None, project_domains: List[str]) -> int:
    if course is None:
        return 0
    return {"core": 2, "general": 1}.get(course_curriculum_role(course, project_domains), 0)


def education_level_course_allowed(course: Course, education_level: str | None) -> bool:
    """Reject courses whose title explicitly belongs to another degree level."""
    level = str(education_level or "").lower()
    title = title_key(course.title)
    if level in {"bachelor", "undergraduate"}:
        master_only = (
            "история и философия науки",
            "history and philosophy of science",
            "педагогика высшей школы",
            "higher education pedagogy",
            "менеджмент и психология управления",
        )
        return not any(marker in title for marker in master_only)
    if level in {"master", "masters", "magistracy"}:
        bachelor_only = ("история казахстана", "history of kazakhstan")
        return not any(marker in title for marker in bachelor_only)
    return True
