from __future__ import annotations

from typing import Dict, List
from itertools import combinations
import math
import re
import unicodedata
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.bridge_module import BridgeModule
from app.models.course import Course, course_prerequisites
from app.models.embedding import MatchScore
from app.models.plan import Plan, PlanItem
from app.models.project import LearningOutcome, ProjectVersion
from app.models.epvo import EpvoDirection, EpvoDisciplineLoLink, EpvoDisciplineNormalized, EpvoGroup
from app.services.epvo_repository import epvo_row_matches_education_level, epvo_row_relevance_score
from app.planner.international_quality import evaluate_international_quality
from app.planner.verifier import TOTAL_CREDIT_TOLERANCE, verify_curriculum_plan
from app.planner.goso import merge_goso_items


def _remove_item_once(items: List[Dict], item: Dict) -> bool:
    """Remove an item only if it is still present in the source list."""
    try:
        items.remove(item)
        return True
    except ValueError:
        return False


def _move_item(schedule: Dict[int, List[Dict]], source: int, target: int, item: Dict) -> bool:
    """Move an item between semesters without crashing on stale candidates."""
    if source == target:
        return False
    if not _remove_item_once(schedule[source], item):
        return False
    schedule[target].append(item)
    return True


def _swap_items(schedule: Dict[int, List[Dict]], left_semester: int, left_item: Dict, right_semester: int, right_item: Dict) -> bool:
    """Swap two semester items only when both are still present."""
    if left_item not in schedule[left_semester] or right_item not in schedule[right_semester]:
        return False
    schedule[left_semester].remove(left_item)
    schedule[right_semester].remove(right_item)
    schedule[left_semester].append(right_item)
    schedule[right_semester].append(left_item)
    return True


def _title_key(title: str | None) -> str:
    """Canonical course title used to prevent semantic duplicates."""
    value = title or ""
    suspicious = "Ð" in value or "Ñ" in value or (
        len(value) > 6 and (value.count("Р") + value.count("С")) > len(value) / 4
    )
    if suspicious:
        for source_encoding in ("latin1", "cp1251"):
            try:
                repaired = value.encode(source_encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            if repaired and repaired != value:
                value = repaired
                break
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", value, flags=re.UNICODE))


def _short_lo_theme(lo: LearningOutcome | None) -> str:
    """Readable Russian theme for bridge titles; keeps modules distinguishable."""
    text = f"{getattr(lo, 'lo_code', '')} {getattr(lo, 'description_ru', '') or getattr(lo, 'description', '') or getattr(lo, 'lo_text', '') or ''}".lower()
    if any(token in text for token in ("данн", "аналит", "статист", "информац")):
        return "данных и аналитики"
    if any(token in text for token in ("модел", "алгорит", "машин", "ии", "ai", "нейро")):
        return "моделей и алгоритмов"
    if any(token in text for token in ("безопас", "кибер", "угроз", "риск")):
        return "безопасности и рисков"
    if any(token in text for token in ("прав", "этик", "норм", "регулир", "госо")):
        return "нормативных и этических решений"
    if any(token in text for token in ("проект", "команд", "коммуник", "обоснов")):
        return "проектной коммуникации"
    if any(token in text for token in ("внедр", "систем", "архитект", "платформ")):
        return "внедрения цифровых систем"
    code = str(getattr(lo, "lo_code", "") or "").strip()
    return f"результата {code}" if code else "междисциплинарной интеграции"


def _has_domain_term(text: str, terms: tuple[str, ...]) -> bool:
    words = set(text.split())
    for token in terms:
        if not token:
            continue
        if re.fullmatch(r"[a-z0-9]{1,3}", token):
            if token in words:
                return True
            continue
        if " " in token:
            if token in text:
                return True
            continue
        if re.search(rf"\b{re.escape(token)}\w*", text, flags=re.UNICODE):
            return True
    return False


def _unique_items_by_title(items: List[Dict]) -> List[Dict]:
    """Keep one curriculum item per title, even when repository IDs differ."""
    result: List[Dict] = []
    seen: set[str] = set()
    seen_semantic: set[tuple[str, int]] = set()
    for item in items:
        key = _title_key(item.get("title"))
        if _is_component_placeholder_title(key):
            continue
        # Missing titles are still protected by their stable database identity.
        key = key or f"id:{item.get('course_id')}:{item.get('bridge_module_id')}"
        if key in seen:
            continue
        semantic_key = _foundation_equivalent_title_key(key)
        semantic_identity = (semantic_key, int(item.get("credits") or 0))
        if semantic_key and semantic_key != key and semantic_identity in seen_semantic:
            continue
        if semantic_key and semantic_key == key and semantic_identity in seen_semantic:
            continue
        seen.add(key)
        if semantic_key:
            seen_semantic.add(semantic_identity)
        result.append(item)
    return result


def _is_component_placeholder_title(key: str) -> bool:
    """Reject catalogue metadata accidentally imported as a course title."""
    return key in {
        "обязательный компонент",
        "компонент по выбору",
        "вузовский компонент",
        "mandatory component",
        "elective component",
        "university component",
    }


def _foundation_equivalent_title_key(key: str) -> str:
    """Conservatively merge same-credit titles differing only by a foundation prefix."""
    prefixes = (
        "основы ", "введение в ", "введение в основы ", "базовый курс ",
        "fundamentals of ", "introduction to ", "basic course in ",
    )
    for prefix in prefixes:
        if key.startswith(prefix):
            candidate = key[len(prefix):].strip()
            if len(candidate.split()) >= 2:
                return candidate
    return key


def _late_stage_min_semester(title: str | None, num_semesters: int) -> int:
    """Keep internships/thesis/final attestation out of early semesters."""
    key = _title_key(title)
    if not key:
        return 1
    final_markers = (
        "преддиплом", "диплом", "итоговая аттестация", "final attestation",
        "thesis", "graduation", "capstone defense",
    )
    practice_markers = ("практика", "practice", "internship")
    if any(marker in key for marker in final_markers):
        return max(1, num_semesters - 1)
    if any(marker in key for marker in practice_markers):
        return max(1, num_semesters - 2)
    return 1


def _complexity_min_semester(item: Dict, num_semesters: int) -> int:
    """Prevent advanced infrastructure/tooling courses from being placed as first-semester foundations."""
    # ГОСО research/practice/final blocks already carry normative semester
    # placement. Numeric suffixes such as "НИРД 2" are sequence numbers, not
    # generic indicators of an advanced elective course.
    if item.get("regulatory_required") and str(item.get("type") or "").startswith("goso_"):
        return 1
    # Use the course title and component type for complexity.  The legacy
    # `domain` field can be stale for canonical EPVO courses reused across
    # programmes (for example a basic algorithms course imported earlier under
    # "forensics").  Domain scope is checked elsewhere; using it here creates
    # false "too early" warnings for valid first-year foundations.
    text = _title_key(" ".join([
        item.get("title") or "",
        item.get("type") or "",
    ]))
    advanced_terms = (
        "kafka", "mqtt", "spark", "hadoop", "stream", "потоков",
        "микросервис", "microservice", "devops", "kubernetes", "docker",
        "облач", "cloud", "distributed", "распредел", "big data",
        "machine learning", "deep learning", "нейросет", "malware",
        "реверс", "reverse", "форензик", "forensic", "siem", "soc",
    )
    clinical_advanced_terms = (
        "хирург", "surgery", "кардио", "гастро", "онколог", "уролог",
        "невролог", "паразитолог", "психиатр", "офтальм", "реаним",
        "терапи", "педиатр", "акуш", "гинек", "дермат", "клиническ",
    )
    research_terms = (
        "методология науч", "scientific methodology", "доказательная медицина",
        "evidence based medicine", "научных исследований", "research methods",
    )
    if _has_domain_term(text, clinical_advanced_terms):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.55)))
    if _has_domain_term(text, research_terms):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.35)))
    if "первичной медицинской помощи" in text or "primary medical care" in text:
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.45)))
    if "продвинут" in text or "advanced" in text or re.search(r"\b[23]\b", text):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.45)))
    if _has_domain_term(text, advanced_terms):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.35)))
    return 1


def _foundation_max_semester(title: str | None, num_semesters: int) -> int:
    key = _title_key(title)
    if any(marker in key for marker in (
        "информационной безопасности", "кибербезопасности",
        "цифровой криминалистики", "digital forensics", "cybersecurity",
    )):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.65)))
    if any(marker in key for marker in (
        "доказательной медицины", "evidence based medicine",
    )):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.9)))
    if any(marker in key for marker in (
        "научных исследований", "research methods", "academic writing",
    )):
        return max(2, min(num_semesters, math.ceil(num_semesters * 0.5)))
    foundation_markers = (
        "основы ", "введение ", "теоретические основы",
        "fundamentals", "introduction", "инструментарий технологии программирования",
    )
    if key.startswith(("основы ", "введение ")) or any(
        marker in key for marker in foundation_markers[2:]
    ):
        return max(1, min(num_semesters, math.ceil(num_semesters * 0.35)))
    return num_semesters


def _is_interdisciplinary_title_relevant(course: Course, project_domains: List[str]) -> bool:
    """Require a course to fit the professional role of its project domain.

    EPVO groups legitimately contain general education and elective noise.  For
    interdisciplinary generation the plan core should be selected by positive
    domain fit, not by a growing list of forbidden titles.
    """
    domains = " ".join(project_domains).lower()
    has_it = "it" in domains or "информ" in domains or "computer" in domains or "кибер" in domains
    has_forensics = "forensic" in domains or "криминал" in domains or "расслед" in domains or "след" in domains
    if not (("medicine" in domains or "мед" in domains or "здрав" in domains) and ("it" in domains or "информ" in domains or "computer" in domains)):
        if not (has_it and has_forensics):
            return True
    full_text = _title_key(" ".join([course.title or "", course.description or ""]))
    if not full_text:
        return False
    medical_terms = (
        "мед", "здрав", "клиник", "пациент", "врач", "био", "анатом", "физиолог",
        "фармак", "эпидеми", "вирус", "бактер", "гистолог", "иммун", "хирург",
        "инфекц", "патолог", "онколог", "уролог", "невролог", "педиатр",
    )
    it_terms = (
        "it", "информ", "цифр", "данн", "data", "программ", "алгоритм",
        "автомат", "ai", "искусствен", "модел", "mathlab", "3d", "телемед",
        "сеть", "сетей", "баз", "cloud", "облач", "machine learning",
        "кибер", "безопас", "сервер", "вычисл", "software", "computer",
    )
    forensic_terms = (
        "forensic", "криминалист", "расслед", "доказател", "экспертн",
        "судеб", "процессу", "инцидент", "угроз", "вредонос",
        "malware", "киберпреступ", "цифров", "журнал", "лог", "osint",
        "атак", "уязвим", "сохранен", "документирован", "цепочк",
    )
    domain = (course.domain or "").lower()
    if has_it and has_forensics:
        if not _has_domain_term(full_text, it_terms + forensic_terms):
            return False
        if "forensic" in domain or "криминал" in domain or "расслед" in domain or "след" in domain:
            return _has_domain_term(full_text, forensic_terms)
        if "it" in domain or "информ" in domain or "computer" in domain or "кибер" in domain:
            return _has_domain_term(full_text, it_terms + forensic_terms)
        return _has_domain_term(full_text, it_terms + forensic_terms)
    if "medicine" in domain or "мед" in domain or "здрав" in domain:
        return _has_domain_term(full_text, medical_terms)
    if "it" in domain or "информ" in domain or "computer" in domain:
        return _has_domain_term(full_text, it_terms)
    return True


def _course_domain_matches(course: Course, project_domains: List[str]) -> bool:
    domain = (course.domain or "").lower().strip()
    return bool(domain) and any(d and (d in domain or domain in d) for d in project_domains)


def _is_invalid_project_domain_label(value: str | None) -> bool:
    normalized = _title_key(value)
    if not normalized:
        return True
    if "?" in normalized:
        return True
    alpha_count = sum(1 for char in normalized if char.isalpha())
    return alpha_count < 3


def _project_domain_terms(project_version: ProjectVersion, db: Session) -> List[str]:
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
        if not _is_invalid_project_domain_label(str(value or "")):
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
        key = _title_key(value)
        if key and key not in seen and not _is_invalid_project_domain_label(value):
            seen.add(key)
            result.append(value)
    return result


def _course_curriculum_role(course: Course, project_domains: List[str]) -> str:
    title = _title_key(course.title)
    general_title_terms = (
        "основы экономики", "финансовой грамотности", "правовые основы",
        "основы права", "антикорруп", "академическ", "социально политическ",
        "безопасности жизнедеятельности", "устойчивого развития",
        "история медицины", "психология управления", "иностранный язык",
        "foreign language", "введение в профессию", "методология научного исследования",
        "организация и планирование научных исследований",
        "экономика устойчивого развития", "история медицины",
        "правовые основы бизнеса", "педагогика и валеология",
        "современные проблемы менеджмента", "менеджмент программных проектов",
        "введение в научные исследования", "medical interview and basics of medical ethics",
    )
    if ("язык" in title or "language" in title) and not any(
        marker in title for marker in ("программ", "programming", "анализа данных", "data analysis")
    ):
        return "general"
    if any(term in title for term in general_title_terms):
        return "general"
    if not _course_domain_matches(course, project_domains):
        return "other"
    domains = " ".join(project_domains).lower()
    has_it = "it" in domains or "информ" in domains or "computer" in domains or "кибер" in domains
    has_forensics = "forensic" in domains or "криминал" in domains or "расслед" in domains
    if has_it and has_forensics:
        text = _title_key(" ".join([course.title or "", course.description or ""]))
        cyber_terms = (
            "кибер", "безопас", "защит", "сеть", "сетей", "сервер",
            "forensic", "форензик", "криминалист", "расслед", "доказател",
            "экспертн", "судеб", "процессу", "инцидент", "угроз", "вредонос",
            "malware", "киберпреступ", "атак", "уязвим", "osint", "лог", "журнал",
            "цепочк", "документирован",
        )
        if not _has_domain_term(text, cyber_terms):
            return "general"
    return "core" if _is_interdisciplinary_title_relevant(course, project_domains) else "general"


def _course_role_rank(course: Course | None, project_domains: List[str]) -> int:
    if course is None:
        return 0
    return {"core": 2, "general": 1}.get(_course_curriculum_role(course, project_domains), 0)


def _education_level_course_allowed(course: Course, education_level: str | None) -> bool:
    """Reject courses whose title explicitly belongs to another degree level."""
    level = str(education_level or "").lower()
    title = _title_key(course.title)
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


def _audit_final_course_admission(schedule: Dict, project_version: ProjectVersion, db: Session) -> Dict:
    """Verify that every persisted real course has auditable admission evidence."""
    constraints = project_version.project.constraints_json or {}
    jurisdiction_kz = str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() == "KZ"
    total_semesters = int(constraints.get("total_semesters", 8) or 8)
    project_domains = _project_domain_terms(project_version, db)
    real_items = [
        (int(semester), item)
        for semester, items in schedule.items()
        for item in items if item.get("course_id") is not None
    ]
    course_ids = {int(item["course_id"]) for _, item in real_items}
    courses = {course.id: course for course in db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()}
    lo_codes = {lo.id: str(lo.lo_code or "") for lo in project_version.learning_outcomes}
    credible_professional: Dict[int, set[str]] = {}
    for match in db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version.id,
        MatchScore.course_id.in_(course_ids or [-1]),
    ).all():
        expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        code = lo_codes.get(match.lo_id, "")
        if code and not code.startswith("LO-GOSO-") and max(float(match.score or 0.0), expert) >= 0.4:
            credible_professional.setdefault(int(match.course_id), set()).add(code)

    scope_pairs = [(
        str(constraints.get("group_code") or ""), str(constraints.get("direction_code") or ""),
    )]
    if str(constraints.get("program_type") or "").lower() in {"interdisciplinary", "joint"}:
        scope_pairs.append((
            str(constraints.get("secondary_group_code") or ""),
            str(constraints.get("secondary_direction_code") or ""),
        ))
    scoped_epvo_ids: set[int] = set()
    if course_ids:
        rows = db.query(EpvoDisciplineNormalized).filter(
            EpvoDisciplineNormalized.approved_course_id.in_(course_ids)
        ).all()
        for row in rows:
            if not epvo_row_matches_education_level(row, constraints.get("education_level")):
                continue
            row_groups = {str(value or "") for value in (row.group_codes or [])}
            row_directions = {str(value or "") for value in (row.direction_codes or [])}
            if any(
                (group and group in row_groups) or (direction and direction in row_directions)
                for group, direction in scope_pairs
            ):
                scoped_epvo_ids.add(int(row.approved_course_id))

    violations = []
    for semester, item in real_items:
        course = courses.get(int(item["course_id"]))
        if not course:
            violations.append({"course_id": item["course_id"], "title": item.get("title"), "reason": "missing_course"})
            continue
        code = str(course.course_id or "")
        if code.startswith("GOSO-KZ-") and jurisdiction_kz:
            continue
        reason = None
        if code.startswith("GOSO-KZ-"):
            reason = "goso_outside_kz_mode"
        elif not _education_level_course_allowed(course, constraints.get("education_level")):
            reason = "wrong_education_level"
        elif code.startswith("EPVO-") and course.id not in scoped_epvo_ids:
            reason = "outside_epvo_scope"
        elif not credible_professional.get(course.id):
            reason = "no_credible_professional_lo"
        elif (
            course.id not in scoped_epvo_ids
            and not code.startswith("EPVO-")
            and not code.startswith(f"AI-CONFIRMED-{project_version.id}-")
            and not _course_domain_matches(course, project_domains)
        ):
            reason = "outside_project_domain"
        else:
            minimum_semester = max(
                _late_stage_min_semester(course.title, total_semesters),
                _complexity_min_semester({
                    "title": course.title,
                    "domain": item.get("domain") or course.domain,
                    "type": item.get("type") or course.cycle_component,
                }, total_semesters),
            )
            if semester < minimum_semester:
                reason = "too_early_for_complexity"
        if reason:
            violations.append({
                "course_id": course.id, "title": course.title,
                "semester": semester, "reason": reason,
            })
    return {"checked_real_courses": len(real_items), "passed": not violations, "violations": violations}


def _limit_general_course_items(
    items: List[Dict],
    courses: Dict[int, Course],
    project_domains: List[str],
    target_credits: int,
    max_percent: int = 20,
) -> List[Dict]:
    """Keep generic/domain-adjacent courses as support, not as programme core."""
    if not items:
        return items
    max_general_credits = max(0, math.floor(target_credits * max_percent / 100))
    normalized = [dict(item) for item in items]
    selected_ids = {item.get("course_id") for item in normalized if item.get("course_id") is not None}
    protected_ids = {
        prerequisite_id
        for item in normalized
        for prerequisite_id in (item.get("prerequisites") or [])
        if prerequisite_id in selected_ids
    }
    general_indexes = []
    general_credits = 0
    for index, item in enumerate(normalized):
        course_id = item.get("course_id")
        course = courses.get(course_id)
        if course and _course_curriculum_role(course, project_domains) == "general":
            credits = int(item.get("credits") or course.credits or 0)
            general_credits += credits
            if course_id not in protected_ids:
                general_indexes.append((index, credits, _course_role_rank(course, project_domains), int(course_id or 0)))
    if general_credits <= max_general_credits:
        return normalized
    remove_indexes = set()
    for index, credits, _rank, _cid in sorted(general_indexes, key=lambda row: (row[2], row[3])):
        if general_credits <= max_general_credits:
            break
        remove_indexes.add(index)
        general_credits -= credits
    return [item for index, item in enumerate(normalized) if index not in remove_indexes]


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
        item["latest_semester"] = recommended + 1
    return item


def _force_bridge_item(items: List[Dict], module: BridgeModule | None, variant_type: str = "A") -> List[Dict]:
    if module is None or any(item.get("bridge_module_id") == module.id for item in items):
        return items
    normalized = [dict(item) for item in items]
    protected_course_ids = {
        prerequisite_id
        for item in normalized
        for prerequisite_id in (item.get("prerequisites") or [])
    }
    bridge = _bridge_item(module)
    same_credit = [
        (index, item) for index, item in enumerate(normalized)
        if item.get("course_id") is not None
        and item.get("course_id") not in protected_course_ids
        and int(item.get("credits") or 0) == int(module.credits or 5)
    ]
    replaceable = same_credit or [
        (index, item) for index, item in enumerate(normalized)
        if item.get("course_id") is not None
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


def _relocate_bounded_bridges(schedule: Dict[int, List[Dict]], num_semesters: int, nominal_load: int, db: Session) -> Dict[int, List[Dict]]:
    """Move CORE/SECONDARY bridge modules back to their intended study window."""
    upper = nominal_load + 3
    loads = {
        semester: sum(int(item.get("credits") or 0) for item in items)
        for semester, items in schedule.items()
    }
    for current_semester in sorted(schedule):
        for item in list(schedule[current_semester]):
            bridge_id = item.get("bridge_module_id")
            if bridge_id is None:
                continue
            bridge = db.query(BridgeModule).filter(BridgeModule.id == bridge_id).first()
            if not bridge or not (bridge.course_id or "").startswith(("CORE_BRIDGE_", "SECONDARY_")):
                continue
            recommended = int(bridge.recommended_semester or item.get("recommended_semester") or 1)
            latest = min(num_semesters, recommended + 1)
            if recommended <= current_semester <= latest:
                continue
            credits = int(item.get("credits") or 0)
            candidates = list(range(recommended, latest + 1))
            candidates.sort(key=lambda semester: (loads[semester] + credits > upper, abs(semester - recommended), loads[semester]))
            target = candidates[0]
            if target == current_semester:
                continue
            if not _move_item(schedule, current_semester, target, item):
                continue
            loads[current_semester] -= credits
            loads[target] += credits
    return schedule


def _rebalance_semester_load(schedule: Dict[int, List[Dict]], num_semesters: int, nominal_load: int) -> Dict[int, List[Dict]]:
    """Final load repair that preserves prerequisite order."""
    lower = nominal_load - 3
    upper = nominal_load + 3

    def loads() -> Dict[int, int]:
        return {semester: sum(int(item.get("credits") or 0) for item in items) for semester, items in schedule.items()}

    def semester_by_course() -> Dict[int, int]:
        return {
            item["course_id"]: semester
            for semester, items in schedule.items()
            for item in items
            if item.get("course_id") is not None
        }

    def dependents() -> Dict[int, List[int]]:
        result: Dict[int, List[int]] = {}
        for items in schedule.values():
            for item in items:
                cid = item.get("course_id")
                if cid is None:
                    continue
                for prerequisite_id in item.get("prerequisites") or []:
                    result.setdefault(prerequisite_id, []).append(cid)
        return result

    for _ in range(40):
        current_loads = loads()
        overloaded = [s for s, load in current_loads.items() if load > upper]
        receivers = [s for s, load in current_loads.items() if load < upper]
        if not overloaded or not receivers:
            break
        moved = False
        course_semesters = semester_by_course()
        child_map = dependents()
        for donor in sorted(overloaded, key=lambda s: current_loads[s], reverse=True):
            for target in sorted((s for s in receivers if s != donor), key=lambda s: current_loads[s]):
                for item in sorted(list(schedule[donor]), key=lambda x: int(x.get("credits") or 0), reverse=True):
                    if item.get("regulatory_required"):
                        continue
                    credits = int(item.get("credits") or 0)
                    if current_loads[target] + credits > upper:
                        continue
                    if target < max(
                        _late_stage_min_semester(item.get("title"), num_semesters),
                        _complexity_min_semester(item, num_semesters),
                    ):
                        continue
                    latest = int(item.get("latest_semester") or num_semesters)
                    if target > latest:
                        continue
                    parent_semesters = [course_semesters.get(pid, 0) for pid in item.get("prerequisites") or []]
                    if parent_semesters and max(parent_semesters) >= target:
                        continue
                    cid = item.get("course_id")
                    child_semesters = [course_semesters.get(child_id, num_semesters + 1) for child_id in child_map.get(cid, [])]
                    if child_semesters and min(child_semesters) <= target:
                        continue
                    if not _move_item(schedule, donor, target, item):
                        continue
                    moved = True
                    break
                if moved:
                    break
            if moved:
                break
        if not moved:
            break
    for _ in range(40):
        current_loads = loads()
        underloaded = [s for s, load in current_loads.items() if load < lower]
        donors = [s for s, load in current_loads.items() if load > lower]
        if not underloaded or not donors:
            break
        moved = False
        course_semesters = semester_by_course()
        child_map = dependents()
        for target in sorted(underloaded, key=lambda s: current_loads[s]):
            for donor in sorted((s for s in donors if s != target), key=lambda s: current_loads[s], reverse=True):
                for item in sorted(list(schedule[donor]), key=lambda x: int(x.get("credits") or 0)):
                    if item.get("regulatory_required"):
                        continue
                    credits = int(item.get("credits") or 0)
                    if current_loads[donor] - credits < lower:
                        continue
                    if current_loads[target] + credits > upper:
                        continue
                    if target < max(
                        _late_stage_min_semester(item.get("title"), num_semesters),
                        _complexity_min_semester(item, num_semesters),
                    ):
                        continue
                    latest = int(item.get("latest_semester") or num_semesters)
                    if target > latest:
                        continue
                    parent_semesters = [course_semesters.get(pid, 0) for pid in item.get("prerequisites") or []]
                    if parent_semesters and max(parent_semesters) >= target:
                        continue
                    cid = item.get("course_id")
                    child_semesters = [course_semesters.get(child_id, num_semesters + 1) for child_id in child_map.get(cid, [])]
                    if child_semesters and min(child_semesters) <= target:
                        continue
                    if not _move_item(schedule, donor, target, item):
                        continue
                    moved = True
                    break
                if moved:
                    break
            if moved:
                break
        if not moved:
            break

    # A whole-course move cannot repair common 26/34 or 26/32 splits when all
    # courses carry 3--5 credits.  Exchange a larger donor course for a smaller
    # receiver course, while preserving every prerequisite and semester bound.
    for _ in range(40):
        current_loads = loads()
        underloaded = [s for s, load in current_loads.items() if load < lower]
        if not underloaded:
            break
        course_semesters = semester_by_course()
        child_map = dependents()
        swapped = False

        def can_place(item: Dict, target: int, overrides: Dict[int, int]) -> bool:
            if item.get("regulatory_required"):
                return False
            if target < max(
                _late_stage_min_semester(item.get("title"), num_semesters),
                _complexity_min_semester(item, num_semesters),
            ):
                return False
            if target > int(item.get("latest_semester") or num_semesters):
                return False
            cid = item.get("course_id")
            parent_semesters = [
                overrides.get(pid, course_semesters.get(pid, 0))
                for pid in item.get("prerequisites") or []
            ]
            if parent_semesters and max(parent_semesters) >= target:
                return False
            child_semesters = [
                overrides.get(child_id, course_semesters.get(child_id, num_semesters + 1))
                for child_id in child_map.get(cid, [])
            ] if cid is not None else []
            return not child_semesters or min(child_semesters) > target

        for target in sorted(underloaded, key=lambda s: current_loads[s]):
            donors = sorted(
                (s for s in schedule if s != target and current_loads[s] > lower),
                key=lambda s: current_loads[s],
                reverse=True,
            )
            for donor in donors:
                for donor_item in sorted(schedule[donor], key=lambda row: int(row.get("credits") or 0), reverse=True):
                    donor_credits = int(donor_item.get("credits") or 0)
                    for target_item in sorted(schedule[target], key=lambda row: int(row.get("credits") or 0)):
                        target_credits = int(target_item.get("credits") or 0)
                        if donor_credits <= target_credits:
                            continue
                        new_target_load = current_loads[target] - target_credits + donor_credits
                        new_donor_load = current_loads[donor] - donor_credits + target_credits
                        if not (lower <= new_target_load <= upper and lower <= new_donor_load <= upper):
                            continue
                        overrides = {}
                        if donor_item.get("course_id") is not None:
                            overrides[int(donor_item["course_id"])] = target
                        if target_item.get("course_id") is not None:
                            overrides[int(target_item["course_id"])] = donor
                        if not can_place(donor_item, target, overrides) or not can_place(target_item, donor, overrides):
                            continue
                        if not _swap_items(schedule, donor, donor_item, target, target_item):
                            continue
                        swapped = True
                        break
                    if swapped:
                        break
                if swapped:
                    break
            if swapped:
                break
        if not swapped:
            break
    return schedule


def _strict_rebalance_max_load(schedule: Dict[int, List[Dict]], num_semesters: int, max_load: int) -> Dict[int, List[Dict]]:
    """Try to respect the user-entered maximum semester load exactly."""
    if max_load <= 0:
        return schedule

    def loads() -> Dict[int, int]:
        return {semester: sum(int(item.get("credits") or 0) for item in items) for semester, items in schedule.items()}

    def semester_by_course() -> Dict[int, int]:
        return {
            item["course_id"]: semester
            for semester, items in schedule.items()
            for item in items
            if item.get("course_id") is not None
        }

    def dependents() -> Dict[int, List[int]]:
        result: Dict[int, List[int]] = {}
        for items in schedule.values():
            for item in items:
                cid = item.get("course_id")
                if cid is None:
                    continue
                for prerequisite_id in item.get("prerequisites") or []:
                    result.setdefault(prerequisite_id, []).append(cid)
        return result

    for _ in range(80):
        current = loads()
        overloaded = [semester for semester, load in current.items() if load > max_load]
        if not overloaded:
            break
        moved = False
        course_semesters = semester_by_course()
        child_map = dependents()
        for donor in sorted(overloaded, key=lambda semester: current[semester], reverse=True):
            for item in sorted(list(schedule[donor]), key=lambda row: int(row.get("credits") or 0)):
                if item.get("regulatory_required"):
                    continue
                credits = int(item.get("credits") or 0)
                if credits <= 0:
                    continue
                latest = int(item.get("latest_semester") or num_semesters)
                earliest = max(
                    _late_stage_min_semester(item.get("title"), num_semesters),
                    _complexity_min_semester(item, num_semesters),
                )
                parent_semesters = [course_semesters.get(pid, 0) for pid in item.get("prerequisites") or []]
                min_target = max([earliest, *(semester + 1 for semester in parent_semesters)])
                cid = item.get("course_id")
                child_semesters = [course_semesters.get(child_id, num_semesters + 1) for child_id in child_map.get(cid, [])]
                semantic_latest = _foundation_max_semester(item.get("title"), num_semesters)
                if item.get("prerequisites") or int(item.get("recommended_semester") or 0) >= 4:
                    semantic_latest = max(
                        semantic_latest,
                        min(num_semesters, int(item.get("recommended_semester") or 1) + 2),
                    )
                max_target = min([latest, semantic_latest, *(semester - 1 for semester in child_semesters)] or [latest])
                targets = [
                    semester for semester in range(min_target, max_target + 1)
                    if semester != donor and current.get(semester, 0) + credits <= max_load
                ]
                if not targets:
                    continue
                targets.sort(key=lambda semester: (abs(semester - int(item.get("recommended_semester") or semester)), current.get(semester, 0)))
                target = targets[0]
                if not _move_item(schedule, donor, target, item):
                    continue
                current[donor] -= credits
                current[target] += credits
                moved = True
                break
            if moved:
                break
        if not moved:
            # A direct move can be blocked when every early receiver is full.
            # Free one valid receiver by moving one of its flexible courses to
            # a later semester, then place the overloaded course.  This is a
            # bounded two-hop move; it never moves ГОСО units or breaks a
            # prerequisite edge.
            def can_place(candidate: Dict, target: int, overrides: Dict[int, int]) -> bool:
                if candidate.get("regulatory_required"):
                    return False
                if target < max(
                    _late_stage_min_semester(candidate.get("title"), num_semesters),
                    _complexity_min_semester(candidate, num_semesters),
                ):
                    return False
                if target > int(candidate.get("latest_semester") or num_semesters):
                    return False
                semantic_latest = _foundation_max_semester(candidate.get("title"), num_semesters)
                if candidate.get("prerequisites") or int(candidate.get("recommended_semester") or 0) >= 4:
                    semantic_latest = max(
                        semantic_latest,
                        min(num_semesters, int(candidate.get("recommended_semester") or 1) + 2),
                    )
                if target > semantic_latest:
                    return False
                parents = [
                    overrides.get(pid, course_semesters.get(pid, 0))
                    for pid in candidate.get("prerequisites") or []
                ]
                if parents and max(parents) >= target:
                    return False
                cid = candidate.get("course_id")
                children = [
                    overrides.get(child, course_semesters.get(child, num_semesters + 1))
                    for child in child_map.get(cid, [])
                ] if cid is not None else []
                return not children or min(children) > target

            cascaded = False
            for donor in sorted(overloaded, key=lambda semester: current[semester], reverse=True):
                for donor_item in sorted(schedule[donor], key=lambda row: int(row.get("credits") or 0), reverse=True):
                    if donor_item.get("regulatory_required"):
                        continue
                    donor_credits = int(donor_item.get("credits") or 0)
                    for target in range(1, num_semesters + 1):
                        if target == donor or not can_place(donor_item, target, {}):
                            continue
                        for displaced in sorted(schedule[target], key=lambda row: int(row.get("credits") or 0)):
                            if displaced.get("regulatory_required"):
                                continue
                            displaced_credits = int(displaced.get("credits") or 0)
                            if current[target] - displaced_credits + donor_credits > max_load:
                                continue
                            for receiver in sorted(
                                (semester for semester in schedule if semester not in {donor, target}),
                                key=lambda semester: current[semester],
                            ):
                                if current[receiver] + displaced_credits > max_load:
                                    continue
                                overrides = {}
                                if donor_item.get("course_id") is not None:
                                    overrides[int(donor_item["course_id"])] = target
                                if displaced.get("course_id") is not None:
                                    overrides[int(displaced["course_id"])] = receiver
                                if not can_place(donor_item, target, overrides) or not can_place(displaced, receiver, overrides):
                                    continue
                                if not _move_item(schedule, donor, target, donor_item):
                                    continue
                                if not _move_item(schedule, target, receiver, displaced):
                                    _move_item(schedule, target, donor, donor_item)
                                    continue
                                cascaded = True
                                break
                            if cascaded:
                                break
                        if cascaded:
                            break
                    if cascaded:
                        break
                if cascaded:
                    break
            if not cascaded:
                break
    return schedule


def _repair_semester_appropriateness(
    schedule: Dict[int, List[Dict]],
    num_semesters: int,
    nominal_load: int,
    db: Session,
) -> Dict[int, List[Dict]]:
    """Repair semantic semester bounds without breaking load/prerequisites."""
    course_ids = {
        int(item["course_id"])
        for items in schedule.values()
        for item in items
        if item.get("course_id") is not None
    }
    courses = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()
    }
    lower_load, upper_load = nominal_load - 3, nominal_load + 3

    def bounds(item: Dict) -> tuple[int, int]:
        if item.get("regulatory_required"):
            semester = max(1, min(num_semesters, int(item.get("recommended_semester") or 1)))
            return semester, semester
        course = courses.get(item.get("course_id"))
        if not course:
            return 1, num_semesters
        recommended = int(item.get("recommended_semester") or course.recommended_semester or 0)
        semantic_upper = _foundation_max_semester(course.title, num_semesters)
        if item.get("prerequisites") or recommended >= 4:
            # "Основы" can name a domain foundation built on earlier general
            # prerequisites (for example engineering calculations after
            # mathematics).  In that case the source semester and graph are
            # stronger evidence than the lexical prefix alone.
            semantic_upper = max(semantic_upper, min(num_semesters, recommended + 2))
        recommended_lower = max(1, recommended - 1) if recommended else 1
        # A late semester copied from one source programme must not turn an
        # explicitly introductory course into a capstone. Semantic foundation
        # bounds are authoritative when the two signals conflict.
        if recommended_lower > semantic_upper:
            recommended_lower = 1
        lower = max(
            1,
            _late_stage_min_semester(course.title, num_semesters),
            _complexity_min_semester({
                "title": course.title,
                "domain": item.get("domain") or course.domain,
                "type": item.get("type") or course.cycle_component,
            }, num_semesters),
            recommended_lower,
        )
        upper = max(lower, semantic_upper)
        return lower, min(num_semesters, upper)

    def prerequisites_valid(candidate: Dict[int, List[Dict]]) -> bool:
        semester_by_course = {
            item.get("course_id"): semester
            for semester, items in candidate.items()
            for item in items
            if item.get("course_id") is not None
        }
        return all(
            semester_by_course.get(prerequisite_id, 0) < semester
            for semester, items in candidate.items()
            for item in items
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in semester_by_course
        )

    for _ in range(2):
        changed = False
        loads = {
            semester: sum(int(item.get("credits") or 0) for item in items)
            for semester, items in schedule.items()
        }
        misplaced = [
            (semester, item, *bounds(item))
            for semester, items in schedule.items()
            for item in list(items)
            if item.get("course_id") is not None
            and not (bounds(item)[0] <= semester <= bounds(item)[1])
        ]
        for current, item, lower, upper in misplaced:
            credits = int(item.get("credits") or 0)
            targets = sorted(
                range(lower, upper + 1),
                key=lambda semester: (abs(semester - current), loads.get(semester, 0)),
            )
            repaired = False
            for target in targets:
                if target == current:
                    continue
                if (
                    loads[current] - credits >= lower_load
                    and loads[target] + credits <= upper_load
                ):
                    candidate = {semester: list(items) for semester, items in schedule.items()}
                    if not _move_item(candidate, current, target, item):
                        continue
                    if prerequisites_valid(candidate):
                        schedule = candidate
                        loads[current] -= credits
                        loads[target] += credits
                        repaired = changed = True
                        break
                for other in list(schedule[target]):
                    if other.get("course_id") is None:
                        continue
                    other_credits = int(other.get("credits") or 0)
                    new_current_load = loads[current] - credits + other_credits
                    new_target_load = loads[target] - other_credits + credits
                    if not (
                        lower_load <= new_current_load <= upper_load
                        and lower_load <= new_target_load <= upper_load
                    ):
                        continue
                    other_lower, other_upper = bounds(other)
                    if not (other_lower <= current <= other_upper):
                        continue
                    candidate = {semester: list(items) for semester, items in schedule.items()}
                    if not _swap_items(candidate, current, item, target, other):
                        continue
                    if prerequisites_valid(candidate):
                        schedule = candidate
                        loads[current] = new_current_load
                        loads[target] = new_target_load
                        repaired = changed = True
                        break
                if repaired:
                    break
        if not changed:
            break

    # A one-for-one swap is sometimes impossible when every early semester is
    # full of 3-credit courses while the misplaced foundation has 5 credits.
    # Try a bounded three-way rotation (late -> early -> middle -> late).  This
    # preserves semester loads, semantic bounds and every prerequisite edge.
    for _ in range(3):
        loads = {
            semester: sum(int(item.get("credits") or 0) for item in items)
            for semester, items in schedule.items()
        }
        unresolved = [
            (semester, item, *bounds(item))
            for semester, items in schedule.items()
            for item in list(items)
            if item.get("course_id") is not None
            and not (bounds(item)[0] <= semester <= bounds(item)[1])
        ]
        rotated = False
        for current, item, lower, upper in unresolved:
            item_credits = int(item.get("credits") or 0)
            for target in range(lower, upper + 1):
                if target == current:
                    continue
                for displaced in list(schedule[target]):
                    if displaced.get("regulatory_required") or displaced.get("course_id") is None:
                        continue
                    displaced_credits = int(displaced.get("credits") or 0)
                    for receiver in schedule:
                        if receiver in {current, target}:
                            continue
                        displaced_lower, displaced_upper = bounds(displaced)
                        if not (displaced_lower <= receiver <= displaced_upper):
                            continue
                        for third in list(schedule[receiver]):
                            if third.get("regulatory_required") or third.get("course_id") is None:
                                continue
                            third_lower, third_upper = bounds(third)
                            if not (third_lower <= current <= third_upper):
                                continue
                            third_credits = int(third.get("credits") or 0)
                            candidate_loads = {
                                **loads,
                                current: loads[current] - item_credits + third_credits,
                                target: loads[target] - displaced_credits + item_credits,
                                receiver: loads[receiver] - third_credits + displaced_credits,
                            }
                            if any(
                                not lower_load <= candidate_loads[semester] <= upper_load
                                for semester in (current, target, receiver)
                            ):
                                continue
                            candidate = {semester: list(items) for semester, items in schedule.items()}
                            if not _move_item(candidate, current, target, item):
                                continue
                            if not _move_item(candidate, target, receiver, displaced):
                                continue
                            if not _move_item(candidate, receiver, current, third):
                                continue
                            if not prerequisites_valid(candidate):
                                continue
                            schedule = candidate
                            rotated = True
                            break
                        if rotated:
                            break
                    if rotated:
                        break
                if rotated:
                    break
            if rotated:
                break
        if not rotated:
            break
    return schedule


def _trim_schedule_to_target_credits(schedule: Dict[int, List[Dict]], target_credits: int, db: Session) -> Dict[int, List[Dict]]:
    """Make the persisted schedule prefer the exact programme credit total."""
    def total() -> int:
        return sum(int(item.get("credits") or 0) for items in schedule.values() for item in items)

    for item in sorted(
        (item for items in schedule.values() for item in items if item.get("bridge_module_id") is not None),
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

    for item in sorted(
        (item for items in schedule.values() for item in items if item.get("course_id") is not None and not item.get("regulatory_required")),
        key=lambda row: (
            0 if "выбор" in str(row.get("type") or "").lower() or "elective" in str(row.get("type") or "").lower() else 1,
            -int(row.get("credits") or 0),
            int(row.get("recommended_semester") or 99),
        ),
    ):
        excess = total() - target_credits
        if excess <= 0:
            break
        current = int(item.get("credits") or 0)
        reduction = min(excess, max(0, current - 3))
        if reduction > 0:
            item["credits"] = current - reduction

    while total() > target_credits:
        excess = total() - target_credits
        selected_ids = {
            item.get("course_id")
            for items in schedule.values()
            for item in items
            if item.get("course_id") is not None
            and not item.get("regulatory_required")
        }
        protected = {
            prerequisite_id
            for items in schedule.values()
            for item in items
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in selected_ids
        }
        removable = [
            (semester, index, item)
            for semester, items in schedule.items()
            for index, item in enumerate(items)
            if item.get("course_id") is not None
            and item.get("course_id") not in protected
            and int(item.get("credits") or 0) <= excess
        ]
        if not removable:
            break
        removable.sort(key=lambda row: (
            int(row[2].get("credits") or 0) != excess,
            -row[0],
            int(row[2].get("recommended_semester") or 99),
            int(row[2].get("course_id") or 0),
        ))
        semester, index, _ = removable[0]
        del schedule[semester][index]
    return schedule


def _shift_excess_load_to_balance_modules(
    schedule: Dict[int, List[Dict]],
    project_version: ProjectVersion,
    nominal_load: int,
    db: Session,
) -> Dict[int, List[Dict]]:
    """Move residual overload as credit workload, when whole-course moves are impossible."""
    upper = nominal_load + 3

    def loads() -> Dict[int, int]:
        return {semester: sum(int(item.get("credits") or 0) for item in items) for semester, items in schedule.items()}

    for _ in range(20):
        current = loads()
        donors = [semester for semester, load in current.items() if load > upper]
        receivers = [semester for semester, load in current.items() if load < upper]
        if not donors or not receivers:
            break
        moved = False
        for donor_semester in sorted(donors, key=lambda semester: current[semester], reverse=True):
            excess = current[donor_semester] - upper
            if excess <= 0:
                continue
            donor_items = sorted(
                [
                    item for item in schedule[donor_semester]
                    if int(item.get("credits") or 0) > 3
                    and not item.get("regulatory_required")
                ],
                key=lambda item: (
                    0 if item.get("bridge_module_id") is not None else 1,
                    0 if "выбор" in str(item.get("type") or "").lower() or "elective" in str(item.get("type") or "").lower() else 1,
                    -int(item.get("credits") or 0),
                ),
            )
            if not donor_items:
                continue
            for receiver_semester in sorted(receivers, key=lambda semester: current[semester]):
                room = upper - current[receiver_semester]
                if room <= 0:
                    continue
                donor = donor_items[0]
                shift = min(excess, room, int(donor.get("credits") or 0) - 3)
                if shift <= 0:
                    continue
                if shift < 3:
                    receiver_bridge = next(
                        (item for item in schedule[receiver_semester]
                         if item.get("bridge_module_id") is not None and int(item.get("credits") or 0) + shift <= 7),
                        None,
                    )
                    if receiver_bridge is None:
                        continue
                    donor["credits"] = int(donor.get("credits") or 0) - shift
                    if donor.get("bridge_module_id") is not None:
                        donor_module = db.query(BridgeModule).filter(BridgeModule.id == donor["bridge_module_id"]).first()
                        if donor_module:
                            donor_module.credits = donor["credits"]
                    receiver_bridge["credits"] = int(receiver_bridge.get("credits") or 0) + shift
                    receiver_module = db.query(BridgeModule).filter(BridgeModule.id == receiver_bridge["bridge_module_id"]).first()
                    if receiver_module:
                        receiver_module.credits = receiver_bridge["credits"]
                    moved = True
                    break
                donor["credits"] = int(donor.get("credits") or 0) - shift
                if donor.get("bridge_module_id") is not None:
                    donor_module = db.query(BridgeModule).filter(BridgeModule.id == donor["bridge_module_id"]).first()
                    if donor_module:
                        donor_module.credits = donor["credits"]

                code = f"AUTO_LOAD_SHIFT_{project_version.id}_{receiver_semester}"
                module = db.query(BridgeModule).filter(
                    BridgeModule.project_version_id == project_version.id,
                    BridgeModule.course_id == code,
                ).first()
                if module is None:
                    module = BridgeModule(
                        project_version_id=project_version.id,
                        course_id=code,
                        title=f"Интегрированный модуль выравнивания нагрузки семестра {receiver_semester}",
                        goal="Перенести часть проектной и самостоятельной работы из перегруженного семестра.",
                        description="Модуль фиксирует самостоятельную работу, портфолио и консультации по дисциплинам перегруженного семестра.",
                        credits=shift,
                        recommended_semester=receiver_semester,
                        learning_outcomes=["Подготовить портфолио подтверждений по результатам обучения семестра."],
                        topics=["Портфолио", "Самостоятельная работа", "Консультации", "Рефлексия"],
                        prerequisites=[],
                        assessment_methods=["портфолио", "рефлексивный отчёт"],
                        source_chunks_json=[],
                        generation_params_json={"mode": "load_shift_repair", "from_semester": donor_semester},
                        target_los=[lo.lo_code for lo in project_version.learning_outcomes],
                    )
                    db.add(module)
                    db.flush()
                    schedule[receiver_semester].append({
                        "bridge_module_id": module.id,
                        "title": module.title,
                        "domain": "interdisciplinary",
                        "credits": shift,
                        "recommended_semester": receiver_semester,
                        "latest_semester": receiver_semester,
                        "prerequisites": [],
                        "type": "bridge",
                    })
                else:
                    existing = next((item for item in schedule[receiver_semester] if item.get("bridge_module_id") == module.id), None)
                    module.credits = int(module.credits or 0) + shift
                    if existing:
                        existing["credits"] = int(existing.get("credits") or 0) + shift
                    else:
                        schedule[receiver_semester].append({
                            "bridge_module_id": module.id,
                            "title": module.title,
                            "domain": "interdisciplinary",
                            "credits": shift,
                            "recommended_semester": receiver_semester,
                            "latest_semester": receiver_semester,
                            "prerequisites": [],
                            "type": "bridge",
                        })
                moved = True
                break
            if moved:
                break
        if not moved:
            break
    return schedule


def _repair_underloaded_semesters_with_bridges(
    schedule: Dict[int, List[Dict]],
    project_version: ProjectVersion,
    nominal_load: int,
    target_credits: int,
    maximum_credits: int,
    db: Session,
) -> Dict[int, List[Dict]]:
    """Repair a residual low semester using only flexible bridge workload.

    Whole-course moves remain preferable.  This final repair transfers credits
    between 3--7 credit bridge modules and uses the user-approved total-credit
    tolerance only for a remainder that cannot be transferred safely.
    """
    lower = nominal_load - 3

    def loads() -> Dict[int, int]:
        return {
            semester: sum(int(item.get("credits") or 0) for item in items)
            for semester, items in schedule.items()
        }

    bridge_ids = {
        int(item["bridge_module_id"])
        for items in schedule.values()
        for item in items
        if item.get("bridge_module_id") is not None
    }
    modules = {
        module.id: module
        for module in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids or [-1])).all()
    }

    def bridge_kind(item: Dict) -> str:
        module = modules.get(item.get("bridge_module_id"))
        code = str(module.course_id or "") if module else ""
        if code.startswith("SECONDARY_"):
            return "secondary"
        if code.startswith("CORE_BRIDGE_"):
            return "core"
        return "other"

    for target_semester in sorted(schedule):
        current = loads()
        need = max(0, lower - current.get(target_semester, 0))
        if need <= 0:
            continue
        # Prefer moving a complete flexible bridge.  This keeps every module
        # inside the valid 3--7 credit range and handles residual 26/31 loads
        # without inventing a one-credit pseudo-module.
        whole_bridge_donors = sorted(
            [
                (semester, item)
                for semester, items in schedule.items()
                if semester != target_semester
                for item in items
                if item.get("bridge_module_id") is not None
                and not (item.get("prerequisites") or [])
                and current[semester] - int(item.get("credits") or 0) >= lower
                and current[target_semester] + int(item.get("credits") or 0) <= nominal_load + 3
                and target_semester <= int(item.get("latest_semester") or len(schedule))
            ],
            key=lambda pair: (
                abs(int(pair[1].get("credits") or 0) - need),
                -current[pair[0]],
            ),
        )
        if whole_bridge_donors:
            donor_semester, whole_bridge = whole_bridge_donors[0]
            _move_item(schedule, donor_semester, target_semester, whole_bridge)
            current = loads()
            need = max(0, lower - current.get(target_semester, 0))
            if need <= 0:
                continue
        receivers = sorted(
            [
                item for item in schedule[target_semester]
                if item.get("bridge_module_id") is not None and int(item.get("credits") or 0) < 7
            ],
            key=lambda item: ({"secondary": 0, "other": 1, "core": 2}[bridge_kind(item)], int(item.get("credits") or 0)),
        )
        if not receivers:
            continue
        receiver = receivers[0]
        receiver_kind = bridge_kind(receiver)
        donors = sorted(
            [
                (semester, item)
                for semester, items in schedule.items()
                if semester != target_semester
                for item in items
                if item.get("bridge_module_id") is not None
                and int(item.get("credits") or 0) > 3
                and bridge_kind(item) != receiver_kind
            ],
            key=lambda pair: (0 if bridge_kind(pair[1]) == "core" else 1, -int(pair[1].get("credits") or 0)),
        )
        for donor_semester, donor in donors:
            if need <= 0:
                break
            current = loads()
            transferable = min(
                int(donor.get("credits") or 0) - 3,
                current[donor_semester] - lower,
                7 - int(receiver.get("credits") or 0),
                need,
            )
            if transferable <= 0:
                continue
            donor["credits"] = int(donor.get("credits") or 0) - transferable
            receiver["credits"] = int(receiver.get("credits") or 0) + transferable
            modules[int(donor["bridge_module_id"])].credits = donor["credits"]
            modules[int(receiver["bridge_module_id"])].credits = receiver["credits"]
            need -= transferable

        if need > 0:
            current_total = sum(loads().values())
            increase = min(
                need,
                7 - int(receiver.get("credits") or 0),
                max(0, maximum_credits - current_total),
            )
            if increase > 0:
                receiver["credits"] = int(receiver.get("credits") or 0) + increase
                modules[int(receiver["bridge_module_id"])].credits = receiver["credits"]
    return schedule


def _remap_equivalent_prerequisites(items: List[Dict], db: Session) -> List[Dict]:
    """Point prerequisite clones at the retained same-title course row."""
    normalized = [dict(item) for item in items]
    retained_by_title = {
        _title_key(item.get("title")): item.get("course_id")
        for item in normalized
        if item.get("course_id") is not None
    }
    prerequisite_ids = {
        prerequisite_id
        for item in normalized
        for prerequisite_id in (item.get("prerequisites") or [])
    }
    prerequisite_titles = {
        course.id: _title_key(course.title)
        for course in db.query(Course).filter(Course.id.in_(prerequisite_ids or [-1])).all()
    }
    selected_ids = {value for value in retained_by_title.values() if value is not None}
    for item in normalized:
        remapped = []
        for prerequisite_id in item.get("prerequisites") or []:
            replacement = retained_by_title.get(prerequisite_titles.get(prerequisite_id, ""), prerequisite_id)
            if replacement in selected_ids and replacement != item.get("course_id") and replacement not in remapped:
                remapped.append(replacement)
        item["prerequisites"] = remapped
    return normalized


def _diversify_variant_items(
    items: List[Dict],
    project_version: ProjectVersion,
    db: Session,
    variant_type: str,
    max_swaps: int = 2,
) -> List[Dict]:
    """Keep A/B/C as real alternatives when optimization converges.

    The replacement is conservative: same credits, same project domains, no
    prerequisites, no duplicate title, and no removal of a selected prerequisite.
    """
    if variant_type not in {"B", "C"}:
        return items
    project_domains = _project_domain_terms(project_version, db)
    cyber_forensics_program = (
        any("it" in d or "информ" in d or "computer" in d or "кибер" in d for d in project_domains)
        and any("forensic" in d or "криминал" in d or "расслед" in d for d in project_domains)
    )
    def is_project_domain(course: Course) -> bool:
        if not _course_domain_matches(course, project_domains):
            return False
        if cyber_forensics_program:
            return _course_curriculum_role(course, project_domains) == "core"
        return True

    normalized = [dict(item) for item in items]
    selected_ids = {item.get("course_id") for item in normalized if item.get("course_id") is not None}
    selected_titles = {_title_key(item.get("title")) for item in normalized if item.get("title")}
    protected_ids = {
        prerequisite_id
        for item in normalized
        for prerequisite_id in (item.get("prerequisites") or [])
        if prerequisite_id in selected_ids
    }
    if not selected_ids:
        return normalized

    match_max_by_course = {
        int(row.course_id): float(row.max_score or 0.0)
        for row in db.query(MatchScore.course_id, func.max(MatchScore.score).label("max_score"))
        .filter(MatchScore.project_version_id == project_version.id)
        .group_by(MatchScore.course_id)
        .all()
    }
    alternatives_by_credit: Dict[int, List[Course]] = {}
    for course in db.query(Course).all():
        key = _title_key(course.title)
        if (
            course.id not in selected_ids
            and course.id in match_max_by_course
            and key not in selected_titles
            and is_project_domain(course)
            and match_max_by_course.get(course.id, 0.0) >= 0.4
            and not course.prerequisites
        ):
            alternatives_by_credit.setdefault(int(course.credits or 5), []).append(course)
    for alternatives in alternatives_by_credit.values():
        alternatives.sort(
            key=lambda course: (
                course.recommended_semester or 99,
                course.id if variant_type == "C" else -course.id,
            )
        )

    removable = [
        (index, item)
        for index, item in enumerate(normalized)
        if item.get("course_id") is not None and item.get("course_id") not in protected_ids
    ]
    removable.sort(key=lambda pair: int(pair[1].get("course_id") or 0), reverse=(variant_type == "C"))

    swaps = 0
    for index, item in removable:
        if swaps >= max_swaps:
            break
        credits = int(item.get("credits") or 5)
        candidate = None
        while alternatives_by_credit.get(credits):
            possible = alternatives_by_credit[credits].pop(0)
            possible_title = _title_key(possible.title)
            if possible.id not in selected_ids and possible_title not in selected_titles:
                candidate = possible
                break
        if candidate is None:
            continue
        selected_ids.discard(item.get("course_id"))
        selected_ids.add(candidate.id)
        selected_titles.discard(_title_key(item.get("title")))
        selected_titles.add(_title_key(candidate.title))
        normalized[index] = {
            "course_id": candidate.id,
            "title": candidate.title,
            "domain": candidate.domain,
            "credits": candidate.credits or 5,
            "recommended_semester": candidate.recommended_semester,
            "prerequisites": [],
            "type": candidate.cycle_component or "mandatory",
            "selection_method": item.get("selection_method") or "diversified_alternative",
        }
        swaps += 1
    return normalized


def _normalize_selected_courses_for_quality(
    selected_courses: List[Dict],
    project_version: ProjectVersion,
    db: Session,
    variant_type: str,
) -> List[Dict]:
    """Make the persisted plan reflect the international-quality fix.

    Older generated variants can be valid from a credit perspective but still
    miss the explicit interdisciplinary quality bridge.  This helper applies a
    conservative, auditable normalization to every generator path:
    replace one non-prerequisite 5-credit course with the quality bridge, then
    trim a non-prerequisite elective if the plan remains above the target.
    """
    constraints = project_version.project.constraints_json or {}
    target_credits = int(constraints.get("total_credits", 240))
    quality_bridge = db.query(BridgeModule).filter(
        BridgeModule.project_version_id == project_version.id,
        BridgeModule.course_id == f"QUALITY_BRIDGE_{project_version.id}",
    ).first()

    normalized = [dict(item) for item in selected_courses]

    def total_credits() -> int:
        return sum(int(item.get("credits") or 0) for item in normalized)

    def protected_course_ids() -> set[int]:
        selected_ids = {
            item.get("course_id")
            for item in normalized
            if item.get("course_id") is not None
        }
        return {
            prerequisite_id
            for item in normalized
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in selected_ids
        }

    def relevance(course_id: int | None) -> float:
        if course_id is None:
            return 0.0
        return float(
            sum(
                float(row[0] or 0.0)
                for row in db.query(MatchScore.score)
                .filter(
                    MatchScore.project_version_id == project_version.id,
                    MatchScore.course_id == course_id,
                )
            )
        )

    if quality_bridge and not any(item.get("bridge_module_id") for item in normalized):
        bridge_credits = int(quality_bridge.credits or 5)
        protected = protected_course_ids()
        replaceable = [
            (index, item)
            for index, item in enumerate(normalized)
            if item.get("course_id") is not None
            and item.get("course_id") not in protected
            and int(item.get("credits") or 0) == bridge_credits
        ]
        if replaceable:
            replaceable.sort(
                key=lambda pair: (
                    relevance(pair[1].get("course_id")),
                    int(pair[1].get("recommended_semester") or 99),
                    int(pair[1].get("course_id") or 0),
                )
            )
            offset = {"A": 0, "B": 1, "C": 2}.get(variant_type, 0)
            replace_index, _ = replaceable[offset % min(len(replaceable), 3)]
            normalized[replace_index] = {
                "bridge_module_id": quality_bridge.id,
                "title": quality_bridge.title,
                "domain": "interdisciplinary",
                "credits": bridge_credits,
                "recommended_semester": quality_bridge.recommended_semester,
                "prerequisites": quality_bridge.prerequisites or [],
                "type": "bridge",
            }
        elif total_credits() + bridge_credits <= target_credits + max(0, int(constraints.get("credit_tolerance", TOTAL_CREDIT_TOLERANCE))):
            normalized.append({
                "bridge_module_id": quality_bridge.id,
                "title": quality_bridge.title,
                "domain": "interdisciplinary",
                "credits": bridge_credits,
                "recommended_semester": quality_bridge.recommended_semester,
                "prerequisites": quality_bridge.prerequisites or [],
                "type": "bridge",
            })

    while total_credits() > target_credits:
        excess = total_credits() - target_credits
        protected = protected_course_ids()
        removable = [
            (index, item)
            for index, item in enumerate(normalized)
            if item.get("course_id") is not None
            and item.get("course_id") not in protected
            and total_credits() - int(item.get("credits") or 0) >= target_credits
        ]
        if not removable:
            break
        removable.sort(
            key=lambda pair: (
                int(pair[1].get("credits") or 0) != excess,
                relevance(pair[1].get("course_id")),
                -int(pair[1].get("recommended_semester") or 0),
                int(pair[1].get("course_id") or 0),
            )
        )
        del normalized[removable[0][0]]

    return normalized


def _promote_epvo_priority_courses(
    items: List[Dict],
    courses: Dict[int, Course],
    prereq_ids_by_course: Dict[int, List[int]],
    is_project_domain,
    course_depth,
    num_semesters: int,
    priority_rank,
    target_credits: int,
    maximum_credits: int,
) -> List[Dict]:
    """Prefer real EPVO typical disciplines with expert evidence."""
    result = [dict(item) for item in items]
    selected_ids = {item.get("course_id") for item in result if item.get("course_id") is not None}
    selected_titles = {_title_key(item.get("title")) for item in result if item.get("title")}
    protected_ids = {
        prerequisite_id
        for item in result
        for prerequisite_id in (item.get("prerequisites") or [])
        if prerequisite_id in selected_ids
    }
    total = sum(int(item.get("credits") or 0) for item in result)
    priority_courses = sorted(
        (
            course for course in courses.values()
            if course.id not in selected_ids
            and is_project_domain(course)
            and course_depth(course.id) < num_semesters
            and priority_rank(course) > 0
            and _title_key(course.title) not in selected_titles
        ),
        key=lambda course: (
            priority_rank(course),
            len(prereq_ids_by_course.get(course.id, [])),
            -(course.recommended_semester or 99),
            -course.id,
        ),
        reverse=True,
    )

    promoted = 0
    for course in priority_courses:
        if promoted >= 30:
            break
        prereq_ids = prereq_ids_by_course.get(course.id, [])
        missing_prereqs = [pre_id for pre_id in prereq_ids if pre_id not in selected_ids]
        additions = []
        for pre_id in missing_prereqs:
            pre = courses.get(pre_id)
            if not pre or not is_project_domain(pre) or _title_key(pre.title) in selected_titles:
                additions = []
                break
            additions.append(pre)
        additions.append(course)
        bundle_credits = sum(int(candidate.credits or 5) for candidate in additions)
        if total + bundle_credits <= maximum_credits:
            for candidate in additions:
                result.append({
                    "course_id": candidate.id,
                    "title": candidate.title,
                    "domain": candidate.domain,
                    "credits": candidate.credits or 5,
                    "recommended_semester": candidate.recommended_semester,
                    "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                    "type": candidate.cycle_component or "mandatory",
                    "selection_method": "epvo_priority",
                })
                selected_ids.add(candidate.id)
                selected_titles.add(_title_key(candidate.title))
                total += int(candidate.credits or 5)
            promoted += 1
            continue
        if missing_prereqs:
            continue
        same_credit = int(course.credits or 5)
        replaceable = [
            (index, item)
            for index, item in enumerate(result)
            if item.get("course_id") is not None
            and item.get("course_id") not in protected_ids
            and int(item.get("credits") or 5) == same_credit
            and priority_rank(courses.get(item.get("course_id"))) < priority_rank(course)
        ]
        replaceable.sort(key=lambda pair: priority_rank(courses.get(pair[1].get("course_id"))))
        if not replaceable:
            continue
        index, old_item = replaceable[0]
        selected_ids.discard(old_item.get("course_id"))
        selected_titles.discard(_title_key(old_item.get("title")))
        result[index] = {
            "course_id": course.id,
            "title": course.title,
            "domain": course.domain,
            "credits": course.credits or 5,
            "recommended_semester": course.recommended_semester,
            "prerequisites": prereq_ids,
            "type": course.cycle_component or "mandatory",
            "selection_method": "epvo_priority_replacement",
        }
        selected_ids.add(course.id)
        selected_titles.add(_title_key(course.title))
        promoted += 1
    return _unique_items_by_title(result)


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


def _fit_real_professional_block_after_goso(
    items: List[Dict],
    project_version: ProjectVersion,
    db: Session,
) -> List[Dict]:
    """Fit the post-GOSO professional remainder with whole real courses.

    The general trimmer cannot know that a 155-credit doctoral regulatory
    block leaves an exact 25-credit professional envelope.  Greedy trimming
    used to keep an arbitrary 13-credit subset and fill the remainder with
    bridges.  This bounded dynamic programme maximises real professional LO
    coverage first, evidence second, at the exact remaining credit total.
    """
    constraints = project_version.project.constraints_json or {}
    if str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() != "KZ":
        return items
    target = int(constraints.get("total_credits", 240))
    regulatory = [dict(item) for item in items if item.get("regulatory_required")]
    if not regulatory:
        return items
    capacity = target - sum(int(item.get("credits") or 0) for item in regulatory)
    if capacity <= 0:
        return regulatory
    candidates = _unique_items_by_title([
        dict(item) for item in items
        if item.get("course_id") is not None and not item.get("regulatory_required")
    ])
    if not candidates:
        return items

    professional_los = [
        lo for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    ]
    lo_bit = {lo.id: 1 << index for index, lo in enumerate(professional_los)}
    evidence: Dict[int, tuple[int, float]] = {}
    candidate_ids = [int(item["course_id"]) for item in candidates]
    for match in db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version.id,
        MatchScore.course_id.in_(candidate_ids or [-1]),
        MatchScore.lo_id.in_(list(lo_bit) or [-1]),
    ).all():
        expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        score = max(float(match.score or 0.0), expert)
        if score < 0.5:
            continue
        mask, value = evidence.get(int(match.course_id), (0, 0.0))
        evidence[int(match.course_id)] = (mask | lo_bit[match.lo_id], value + score)

    # (credits, LO mask) -> (evidence utility, selected candidate indexes)
    states: Dict[tuple[int, int], tuple[float, List[int]]] = {(0, 0): (0.0, [])}
    for index, item in enumerate(candidates):
        credits = int(item.get("credits") or 0)
        if credits <= 0 or credits > capacity:
            continue
        mask, utility = evidence.get(int(item["course_id"]), (0, 0.0))
        if not mask:
            continue
        for (used, covered), (current_utility, indexes) in list(states.items())[::-1]:
            new_used = used + credits
            if new_used > capacity:
                continue
            key = (new_used, covered | mask)
            proposal = (current_utility + utility, indexes + [index])
            previous = states.get(key)
            if previous is None or proposal[0] > previous[0]:
                states[key] = proposal

    exact = [(mask, value) for (used, mask), value in states.items() if used == capacity]
    if not exact:
        return items
    best_mask, (_utility, best_indexes) = max(
        exact,
        key=lambda row: (row[0].bit_count(), row[1][0], -len(row[1][1])),
    )
    if best_mask == 0:
        return items
    selected = [candidates[index] for index in best_indexes]
    for item in selected:
        item["selection_method"] = "goso_professional_exact_fit"
    return _unique_items_by_title([*regulatory, *selected])


def build_curriculum_plan(
    project_version_id: int,
    db: Session,
    variant_type: str = "A",
    commit: bool = True,
) -> Dict:
    project_version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not project_version:
        raise ValueError(f"Project version {project_version_id} not found")
    constraints = project_version.project.constraints_json or {}
    excluded_course_ids = {
        int(value) for value in (constraints.get("excluded_course_ids") or [])
        if str(value).isdigit()
    }
    selected_courses = select_courses_for_variant(project_version_id, db, variant_type)
    selected_courses = [
        item for item in selected_courses
        if item.get("course_id") is None or int(item.get("course_id")) not in excluded_course_ids
    ]
    selected_courses = _unique_items_by_title(selected_courses)
    selected_courses = _remap_equivalent_prerequisites(selected_courses, db)
    selected_real_ids = {
        int(item["course_id"]) for item in selected_courses if item.get("course_id") is not None
    }
    # GOSO outcomes are covered by the regulatory block merged immediately
    # after selection.  Requiring ordinary EPVO electives to cover them before
    # that merge made every KZ plan look incomplete and forced synthetic
    # integration bridges into otherwise valid standard programmes.
    professional_los = [
        lo for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    ]
    real_lo_coverage = {lo.id: 0.0 for lo in professional_los}
    if selected_real_ids and real_lo_coverage:
        for match in db.query(MatchScore).filter(
            MatchScore.project_version_id == project_version_id,
            MatchScore.course_id.in_(selected_real_ids),
        ).all():
            expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
            if match.lo_id in real_lo_coverage:
                real_lo_coverage[match.lo_id] = max(
                    real_lo_coverage.get(match.lo_id, 0.0), float(match.score or 0.0), expert
                )
    selector_has_complete_real_lo = bool(real_lo_coverage) and all(
        score >= 0.5 for score in real_lo_coverage.values()
    )
    selector_has_bridges = any(item.get("bridge_module_id") is not None for item in selected_courses)
    if not selector_has_complete_real_lo or selector_has_bridges:
        selected_courses = _normalize_selected_courses_for_quality(selected_courses, project_version, db, variant_type)
    selected_courses = merge_goso_items(selected_courses, project_version, db)
    selected_courses = _fit_real_professional_block_after_goso(
        selected_courses, project_version, db
    )
    confirmed_bridge_ids = {
        int(bridge_id)
        for bridge_id in (constraints.get("confirmed_bridge_replacements") or {})
        if str(bridge_id).isdigit()
    }
    build_program_type = str(constraints.get("program_type") or "standard").lower()
    build_is_interdisciplinary = (
        build_program_type in {"interdisciplinary", "joint"}
        and bool(str(project_version.project.domain2 or "").strip())
    )
    if (
        constraints.get("allow_new_courses", True)
        and build_is_interdisciplinary
        and not selector_has_complete_real_lo
    ):
        for bridge in [
            ensure_core_interdisciplinary_bridge(project_version, db),
            *ensure_secondary_domain_bridge_modules(project_version, db),
        ]:
            if bridge is None or bridge.id in confirmed_bridge_ids:
                continue
            selected_courses = _force_bridge_item(selected_courses, bridge, variant_type)
    if not selector_has_complete_real_lo:
        selected_courses = _ensure_foundation_capacity(selected_courses, project_version, db)
    selected_courses = _unique_items_by_title(selected_courses)
    selected_courses = _remap_equivalent_prerequisites(selected_courses, db)
    num_semesters = int(constraints.get("total_semesters", 8))
    nominal_load = int(constraints.get("max_credits_per_semester", 30))
    target_credits = int(constraints.get("total_credits", 240))
    maximum_credits = target_credits + max(0, int(constraints.get("credit_tolerance", TOTAL_CREDIT_TOLERANCE)))
    selected_courses = _trim_to_target_credits(selected_courses, target_credits, db)
    project_domains = _project_domain_terms(project_version, db)
    interdisciplinary_professional = str(constraints.get("program_type") or "standard").lower() in {"interdisciplinary", "joint"}
    cyber_forensics_program = (
        any("it" in d or "информ" in d or "computer" in d or "кибер" in d for d in project_domains)
        and any("forensic" in d or "криминал" in d or "расслед" in d for d in project_domains)
    )
    match_max_by_course = {
        int(row.course_id): float(row.max_score or 0.0)
        for row in db.query(MatchScore.course_id, func.max(MatchScore.score).label("max_score"))
        .filter(MatchScore.project_version_id == project_version_id)
        .group_by(MatchScore.course_id)
        .all()
    }

    def is_project_domain(course: Course) -> bool:
        if course.id in excluded_course_ids:
            return False
        if not _education_level_course_allowed(course, constraints.get("education_level")):
            return False
        if not _course_domain_matches(course, project_domains):
            return False
        if cyber_forensics_program:
            return _course_curriculum_role(course, project_domains) == "core"
        if interdisciplinary_professional and _course_curriculum_role(course, project_domains) == "general":
            return match_max_by_course.get(course.id, 0.0) >= 0.55
        return True

    def sanitize_selected_courses(items: List[Dict]) -> List[Dict]:
        """Prevent late credit/prerequisite repair from bypassing admission."""
        cleaned = []
        for item in items:
            if item.get("regulatory_required"):
                cleaned.append(item)
                continue
            course_id = item.get("course_id")
            if course_id is None:
                cleaned.append(item)
                continue
            course = db.get(Course, course_id) if course_id else None
            if course is None:
                continue
            code = str(course.course_id or "")
            if code.startswith("GOSO-KZ-") and str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() == "KZ":
                item["regulatory_required"] = True
                cleaned.append(item)
                continue
            if not item.get("admission_los"):
                continue
            if not _education_level_course_allowed(course, constraints.get("education_level")):
                continue
            if course and _course_curriculum_role(course, project_domains) == "general":
                if match_max_by_course.get(course.id, 0.0) < 0.55:
                    continue
            cleaned.append(item)
        return cleaned

    selected_courses = sanitize_selected_courses(selected_courses)
    selected_courses = _trim_to_target_credits(selected_courses, target_credits, db)

    for _ in range(12):
        schedule = schedule_courses(selected_courses, num_semesters, nominal_load, db)
        schedule = _relocate_bounded_bridges(schedule, num_semesters, nominal_load, db)
        verification = verify_curriculum_plan(schedule, project_version, db)
        offending = {item["course_id"] for item in verification["prerequisite_violations"] if item.get("course_id") is not None}
        if not offending: break
        selected_courses = [item for item in selected_courses if item.get("course_id") not in offending]
        selected_ids = {item.get("course_id") for item in selected_courses if item.get("course_id") is not None}
        total = sum(item.get("credits") or 0 for item in selected_courses)
        replacements = [
            course for course in db.query(Course).filter(
                Course.id.in_(list(match_max_by_course) or [-1])
            ).all()
            if course.id not in selected_ids and not course.prerequisites and is_project_domain(course)
        ]
        replacements.sort(key=lambda course: (0 if (course.domain or "").lower() in {(project_version.project.domain1 or "").lower(), (project_version.project.domain2 or "").lower()} else 1, course.credits or 5, course.id))
        for course in replacements:
            credits = course.credits or 5
            if total + credits > maximum_credits: continue
            selected_courses.append({"course_id": course.id, "title": course.title, "domain": course.domain, "credits": credits, "recommended_semester": course.recommended_semester, "prerequisites": [], "type": course.cycle_component or "mandatory"})
            total += credits
            if total >= target_credits: break
        if total < target_credits and constraints.get("allow_new_courses", True):
            existing_bridge_count = sum(1 for item in selected_courses if item.get("bridge_module_id"))
            slots = max(0, int(constraints.get("max_new_courses", 5)) - existing_bridge_count)
            for bm in ensure_credit_bridge_modules(project_version, db, target_credits - total, slots):
                credits = bm.credits or 5
                if total + credits > maximum_credits:
                    continue
                selected_courses.append({
                    "bridge_module_id": bm.id,
                    "title": bm.title,
                    "domain": "interdisciplinary",
                    "credits": credits,
                    "recommended_semester": bm.recommended_semester,
                    "prerequisites": bm.prerequisites or [],
                    "type": "bridge",
                })
                total += credits
                if total >= target_credits:
                    break
        selected_courses = _normalize_selected_courses_for_quality(selected_courses, project_version, db, variant_type)
        selected_courses = merge_goso_items(selected_courses, project_version, db)
        selected_courses = _unique_items_by_title(selected_courses)
        selected_courses = _remap_equivalent_prerequisites(selected_courses, db)
        selected_courses = sanitize_selected_courses(selected_courses)
        selected_courses = _trim_to_target_credits(selected_courses, target_credits, db)

    # Fill an ordinary credit gap with several distinct, auditable modules.
    # Previously the final repair could turn one subject into a 60-credit
    # pseudo-course after duplicate catalogue rows were removed.
    selected_courses = sanitize_selected_courses(selected_courses)
    selected_courses = merge_goso_items(selected_courses, project_version, db)
    total_before_gap_fill = sum(int(item.get("credits") or 0) for item in selected_courses)
    if total_before_gap_fill < target_credits and constraints.get("allow_new_courses", True):
        existing_bridge_ids = {
            item.get("bridge_module_id")
            for item in selected_courses
            if item.get("bridge_module_id") is not None
        }
        configured_bridge_slots = int(constraints.get("max_new_courses", 5))
        credit_gap = max(0, target_credits - total_before_gap_fill)
        maximum_bridge_slots = max(configured_bridge_slots, len(existing_bridge_ids) + math.ceil(credit_gap / 7))
        available_slots = max(0, maximum_bridge_slots - len(existing_bridge_ids))
        for module in ensure_credit_bridge_modules(
            project_version,
            db,
            min(maximum_credits - total_before_gap_fill, target_credits - total_before_gap_fill),
            maximum_bridge_slots,
            desired_count=maximum_bridge_slots,
        ):
            if module.id in existing_bridge_ids:
                continue
            credits = int(module.credits or 5)
            if total_before_gap_fill + credits > maximum_credits:
                continue
            selected_courses.append({
                "bridge_module_id": module.id, "title": module.title,
                "domain": "interdisciplinary", "credits": credits,
                "recommended_semester": module.recommended_semester,
                "prerequisites": module.prerequisites or [], "type": "bridge",
            })
            existing_bridge_ids.add(module.id)
            total_before_gap_fill += credits
            if total_before_gap_fill >= target_credits:
                break

        # Use the permitted 3–7 credit range before inventing another module.
        remaining_gap = max(0, target_credits - total_before_gap_fill)
        for item in reversed(selected_courses):
            if remaining_gap <= 0:
                break
            if item.get("bridge_module_id") is None:
                continue
            room = max(0, 7 - int(item.get("credits") or 0))
            increase = min(room, remaining_gap)
            if increase <= 0:
                continue
            item["credits"] = int(item.get("credits") or 0) + increase
            module = db.query(BridgeModule).filter(BridgeModule.id == item["bridge_module_id"]).first()
            if module:
                module.credits = item["credits"]
            total_before_gap_fill += increase
            remaining_gap -= increase
        selected_courses = _trim_to_target_credits(selected_courses, target_credits, db)

    # Close residual credit/load gaps even when prerequisite verification was
    # already clean. This fixes plans such as 238/240 with a 24-credit semester.
    schedule = schedule_courses(selected_courses, num_semesters, nominal_load, db)
    schedule = _relocate_bounded_bridges(schedule, num_semesters, nominal_load, db)
    provisional = verify_curriculum_plan(schedule, project_version, db)
    total_now = sum(int(item.get("credits") or 0) for item in selected_courses)
    load_gaps = [
        (int(item["semester"]), max(0, math.ceil(item["allowed_min"] - item["credits"])))
        for item in provisional["semester_load_violations"]
        if item.get("credits", 0) < item.get("allowed_min", 0)
    ]
    credit_gap = max(0, target_credits - total_now)
    target_semester, load_gap = max(load_gaps, key=lambda item: item[1], default=(1, 0))
    repair_credits = max(credit_gap, load_gap)
    repair_credits = min(7, repair_credits)
    if 0 < repair_credits < 3:
        repair_credits = 0
    if (repair_credits > 0 and total_now + repair_credits <= maximum_credits
            and constraints.get("allow_new_courses", True)):
        code = f"AUTO_BALANCE_{project_version.id}_{target_semester}"
        balance = db.query(BridgeModule).filter(
            BridgeModule.project_version_id == project_version.id,
            BridgeModule.course_id == code,
        ).first()
        if balance is None:
            balance = BridgeModule(
                project_version_id=project_version.id, course_id=code,
                title=f"Интегрированный практический модуль семестра {target_semester}",
                goal="Сбалансировать нагрузку семестра и подготовить подтверждения достижения результатов обучения.",
                description="Руководимая междисциплинарная практика, портфолио подтверждений и рефлексивная защита.",
                credits=repair_credits, recommended_semester=target_semester,
                learning_outcomes=["Интегрировать знания семестра в прикладной профессиональной задаче."],
                topics=["Интегрированный кейс", "Прикладная практика", "Портфолио подтверждений", "Рефлексия и защита"],
                prerequisites=[], assessment_methods=["портфолио", "проектный кейс", "защита"],
                source_chunks_json=[], generation_params_json={"mode": "final_credit_and_load_repair"},
                target_los=[lo.lo_code for lo in project_version.learning_outcomes],
            )
            db.add(balance); db.flush()
        else:
            balance.credits = repair_credits; balance.recommended_semester = target_semester
        selected_courses.append({
            "bridge_module_id": balance.id, "title": balance.title,
            "domain": "interdisciplinary", "credits": repair_credits,
            "recommended_semester": target_semester, "latest_semester": target_semester,
            "prerequisites": [], "type": "bridge",
        })
        # Direct placement is intentional: running the global scheduler again
        # can move unrelated prerequisite chains and recreate the imbalance.
        schedule[target_semester].append(selected_courses[-1])
        overshoot = total_now + repair_credits - target_credits
        if overshoot > 0:
            loads_after = {
                semester: sum(int(item.get("credits") or 0) for item in items)
                for semester, items in schedule.items()
            }
            donors = sorted(schedule, key=lambda semester: loads_after[semester], reverse=True)
            for donor_semester in donors:
                if loads_after[donor_semester] - overshoot < provisional["allowed_semester_load"]["min"]:
                    continue
                donor = next((item for item in schedule[donor_semester]
                              if item.get("bridge_module_id") not in (None, balance.id)
                              and int(item.get("credits") or 0) > overshoot
                              and int(item.get("credits") or 0) - overshoot >= 3), None)
                if donor is None:
                    continue
                donor["credits"] = int(donor["credits"]) - overshoot
                donor_module = db.query(BridgeModule).filter(BridgeModule.id == donor["bridge_module_id"]).first()
                if donor_module:
                    donor_module.credits = donor["credits"]
                break
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    schedule = _strict_rebalance_max_load(schedule, num_semesters, nominal_load + 3)
    schedule = _trim_schedule_to_target_credits(schedule, target_credits, db)
    schedule = _strict_rebalance_max_load(schedule, num_semesters, nominal_load + 3)
    schedule = _shift_excess_load_to_balance_modules(schedule, project_version, nominal_load, db)
    schedule = _trim_schedule_to_target_credits(schedule, target_credits, db)
    schedule = _repair_semester_appropriateness(
        schedule, num_semesters, nominal_load, db
    )
    schedule = _repair_underloaded_semesters_with_bridges(
        schedule, project_version, nominal_load, target_credits, maximum_credits, db
    )
    # The residual-load repair is intentionally the last credit operation, but
    # it can change which semester has room for a foundation course.  Re-run
    # the semantic repair so the persisted plan, not only the provisional
    # schedule, satisfies the same semester bounds as the verifier.
    schedule = _repair_semester_appropriateness(
        schedule, num_semesters, nominal_load, db
    )

    invalid_domain_courses = []
    for semester_items in schedule.values():
        for item in semester_items:
            if item.get("regulatory_required"):
                continue
            course_id = item.get("course_id")
            if course_id is None:
                continue
            course = db.get(Course, course_id)
            item_domain = str(item.get("domain") or "").lower().strip()
            item_has_project_domain = any(
                domain and (domain in item_domain or item_domain in domain)
                for domain in project_domains
            )
            # The selector rewrites canonical EPVO labels to the exact
            # project-specific direction. Trust that evidence here; canonical
            # Course.domain may come from the first programme that used the
            # deduplicated discipline (for example, "Medicine").
            scoped_admission = item.get("admission_reason") == "epvo_scope_and_lo"
            if course and not (is_project_domain(course) or item_has_project_domain or scoped_admission):
                invalid_domain_courses.append({
                    "course_id": course.id,
                    "title": course.title,
                    "domain": course.domain,
                })
    if invalid_domain_courses:
        raise ValueError(
            "Planner selected courses outside the project domains: "
            + ", ".join(f"{c['title']} ({c['domain']})" for c in invalid_domain_courses[:8])
        )
    admission_audit = _audit_final_course_admission(schedule, project_version, db)
    if not admission_audit["passed"]:
        examples = admission_audit["violations"][:8]
        raise ValueError(
            "Admission filter rejected real courses: "
            + ", ".join(f"{row.get('title')} [{row.get('reason')}]" for row in examples)
        )
    verification = verify_curriculum_plan(schedule, project_version, db)
    metrics = calculate_plan_metrics(schedule, selected_courses, project_version, db, verification)
    metrics["course_admission"] = admission_audit
    plan = Plan(project_version_id=project_version_id, variant_type=variant_type, metrics_json=metrics)
    db.add(plan); db.flush()
    for semester, courses in schedule.items():
        for item in courses:
            db.add(PlanItem(plan_id=plan.id, semester=semester, course_id=item.get("course_id"), bridge_module_id=item.get("bridge_module_id"), credits=item["credits"], course_type=item.get("type", "mandatory"), prerequisites_snapshot=item.get("prerequisites", [])))
    if commit:
        db.commit()
        db.refresh(plan)
    else:
        db.flush()
    semester_los = {}
    semester_lo_details = {}
    lo_by_id = {
        lo.id: lo
        for lo in db.query(LearningOutcome)
        .filter(LearningOutcome.project_version_id == project_version_id)
        .all()
    }
    lo_by_code = {lo.lo_code: lo for lo in lo_by_id.values()}
    for semester, courses in schedule.items():
        evidence = {}
        for item in courses:
            if item.get("course_id"):
                all_rows = db.query(MatchScore).filter(
                    MatchScore.course_id == item["course_id"],
                    MatchScore.project_version_id == project_version_id,
                ).order_by(MatchScore.score.desc()).all()
                rows = [row for row in all_rows if row.score >= 0.4] or all_rows[:1]
                for row in rows:
                    lo = lo_by_id.get(row.lo_id)
                    if lo:
                        detail = evidence.setdefault(lo.lo_code, {
                            "code": lo.lo_code,
                            "text": lo.lo_text,
                            "score": 0.0,
                            "courses": [],
                            "kind": "programme",
                        })
                        detail["score"] = max(detail["score"], round(float(row.score), 3))
                        if item.get("title") not in detail["courses"]:
                            detail["courses"].append(item.get("title"))
            elif item.get("bridge_module_id"):
                bridge = db.query(BridgeModule).filter(BridgeModule.id == item["bridge_module_id"]).first()
                for code in (bridge.target_los or []) if bridge else []:
                    lo = lo_by_code.get(code)
                    if lo:
                        detail = evidence.setdefault(code, {
                            "code": code,
                            "text": lo.lo_text,
                            "score": 0.75,
                            "courses": [],
                            "kind": "programme",
                        })
                        detail["score"] = max(detail["score"], 0.75)
                        if item.get("title") not in detail["courses"]:
                            detail["courses"].append(item.get("title"))
        details = sorted(evidence.values(), key=lambda row: row["code"])
        semester_lo_details[semester] = details
        semester_los[semester] = ", ".join(row["code"] for row in details) if details else "-"
    return {"plan_id": plan.id, "variant_type": variant_type, "schedule": schedule, "metrics": metrics, "verification": verification, "semester_los": semester_los, "semester_lo_details": semester_lo_details}


def select_courses_for_variant(project_version_id: int, db: Session, variant_type: str) -> List[Dict]:
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    constraints = version.project.constraints_json or {}
    target = int(constraints.get("total_credits", 240)); maximum = target + max(0, int(constraints.get("credit_tolerance", TOTAL_CREDIT_TOLERANCE)))
    project_domains = _project_domain_terms(version, db)
    program_type = str(constraints.get("program_type") or "standard").lower()
    interdisciplinary = program_type in {"interdisciplinary", "joint"} and bool(project_domains[1])
    # Integration bridges represent the connection between two independently
    # selected fields.  Forcing them into a standard one-field programme used
    # to replace valid EPVO courses with five synthetic modules.
    allow_bridges = bool(constraints.get("allow_new_courses", True))
    core_bridge = ensure_core_interdisciplinary_bridge(version, db) if allow_bridges and interdisciplinary else None
    secondary_bridges = ensure_secondary_domain_bridge_modules(version, db) if allow_bridges and interdisciplinary else []
    cyber_forensics_program = (
        any("it" in d or "информ" in d or "computer" in d or "кибер" in d for d in project_domains)
        and any("forensic" in d or "криминал" in d or "расслед" in d for d in project_domains)
    )
    interdisciplinary_professional = interdisciplinary
    epvo_professional_scope = any(
        str(constraints.get(key) or "").strip() not in {"", "1", "none", "null"}
        for key in ("group_code", "direction_code", "secondary_group_code", "secondary_direction_code")
    )
    professional_scope = interdisciplinary_professional or epvo_professional_scope or cyber_forensics_program
    default_general_percent = 5 if cyber_forensics_program else 8 if interdisciplinary_professional else 20
    max_general_percent = int(constraints.get("max_general_percent", default_general_percent) or default_general_percent)
    quota_total_credits = int(constraints.get("total_credits", target))
    min_domain_percent = [
        max(0, int(constraints.get("min_domain1_percent") or 0)),
        max(0, int(constraints.get("min_domain2_percent") or 0)) if interdisciplinary else 0,
    ]
    epvo_domain_index: Dict[int, int] = {}
    # Filled from normalized EPVO rows that match both the selected scope and
    # the programme education level. A high semantic score must never allow a
    # bachelor-only catalogue card into a master's/doctoral curriculum.
    epvo_level_scope_allowed_ids: set[int] = set()

    min_general_lo_evidence = 0.55

    def is_project_domain(course: Course) -> bool:
        if not _education_level_course_allowed(course, constraints.get("education_level")):
            return False
        course_code = str(course.course_id or "")
        if course_code.startswith("AI-CONFIRMED-") and not course_code.startswith(f"AI-CONFIRMED-{project_version_id}-"):
            # Expert-confirmed synthetic replacements belong to one project;
            # they must never leak into another curriculum through the global
            # Course table.
            return False
        if course_code.startswith("EPVO-") and course.id not in epvo_level_scope_allowed_ids:
            return False
        # Canonical EPVO courses can be shared by several programmes and keep
        # the global domain label of the first imported row. Exact selected
        # EPVO group/direction evidence is therefore authoritative here.
        if course.id not in epvo_domain_index and not _course_domain_matches(course, project_domains):
            return False
        if professional_scope and not str(course.course_id or "").startswith("GOSO-KZ-"):
            evidence = aggregates.get(course.id, {})
            if (
                epvo_professional_scope
                and str(course.course_id or "").startswith("EPVO-")
                and scope_rank(course) <= 0
                and float(evidence.get("max") or 0.0) < 0.55
            ):
                return False
            # Domain membership alone is insufficient: a medical or IT course
            # may still be irrelevant to this programme's stated outcomes.
            if (
                float(evidence.get("max") or 0.0) < 0.4
                and float(evidence.get("expert") or 0.0) < 0.5
                and not course_code.startswith(f"AI-CONFIRMED-{project_version_id}-")
            ):
                return False
        if cyber_forensics_program:
            return _course_curriculum_role(course, project_domains) == "core"
        if professional_scope and _course_curriculum_role(course, project_domains) == "general":
            evidence = aggregates.get(course.id, {})
            # In interdisciplinary professional programmes generic catalogue
            # items (languages, history, entrepreneurship, etc.) must not fill
            # the curriculum unless they have at least a weak explicit LO link.
            # Otherwise the fallback stage can reach the credit target with
            # courses that are formally in an EPVO group but pedagogically
            # unrelated to the programme outcomes.
            if float(evidence.get("max") or 0.0) < min_general_lo_evidence:
                return False
        return True

    def remove_weak_general_items(items: List[Dict]) -> List[Dict]:
        if not professional_scope:
            return items
        cleaned = []
        for item in items:
            course = courses.get(item.get("course_id"))
            if course and _course_curriculum_role(course, project_domains) == "general":
                evidence = aggregates.get(course.id, {})
                if float(evidence.get("max") or 0.0) < min_general_lo_evidence:
                    continue
            cleaned.append(item)
        return cleaned

    def top_up_with_credit_bridges(items: List[Dict]) -> List[Dict]:
        if not constraints.get("allow_new_courses", True):
            return items
        total_now = sum(int(item.get("credits") or 0) for item in items)
        if total_now >= target:
            return items
        current_bridge_count = sum(1 for item in items if item.get("bridge_module_id") is not None)
        remaining_slots = max(0, int(constraints.get("max_new_courses", 5)) - current_bridge_count)
        if remaining_slots <= 0:
            return items
        auto_modules = ensure_credit_bridge_modules(
            version,
            db,
            min(maximum - total_now, target - total_now),
            remaining_slots,
            desired_count=remaining_slots if variant_type == "C" else None,
        )
        normalized = list(items)
        for bm in auto_modules:
            credits = int(bm.credits or 5)
            if total_now + credits > maximum:
                continue
            bridge = _bridge_item(bm)
            bridge["credits"] = credits
            normalized.append(bridge)
            total_now += credits
            if total_now >= target:
                break
        return normalized

    def close_professional_lo_gaps(items: List[Dict]) -> List[Dict]:
        if not professional_scope:
            return items
        normalized = [dict(item) for item in items]
        lo_by_id = {lo.id: lo for lo in version.learning_outcomes}
        if not lo_by_id:
            return normalized
        selected_course_ids = [int(item["course_id"]) for item in normalized if item.get("course_id")]
        coverage = {lo.lo_code: 0.0 for lo in lo_by_id.values()}
        if selected_course_ids:
            for match in db.query(MatchScore).filter(
                MatchScore.project_version_id == project_version_id,
                MatchScore.course_id.in_(selected_course_ids),
            ).all():
                lo = lo_by_id.get(match.lo_id)
                if lo:
                    coverage[lo.lo_code] = max(coverage.get(lo.lo_code, 0.0), float(match.score or 0.0))
        # A proposed bridge is not evidence that a real discipline covers the
        # outcome.  Real-course gaps remain open until an EPVO/confirmed course
        # reaches the threshold; bridges are reported separately by verifier.
        # Use the same threshold as the verifier.  The old 0.50 repair
        # threshold could leave an LO at 0.55 while the final quality gate
        # correctly required 0.60, producing a plan that the generator itself
        # immediately marked as incomplete.
        required_coverage = float(settings.COVERAGE_THRESHOLD)
        missing = [code for code, score in coverage.items() if score < required_coverage]
        if not missing:
            return normalized

        # Repair LO gaps with real, in-scope EPVO disciplines first.  A bridge
        # is only a last resort when the repository has no sufficiently strong
        # course with the same credit volume.  Expert EPVO evidence is part of
        # the rank, not merely a UI annotation.
        selected_ids = {item.get("course_id") for item in normalized if item.get("course_id") is not None}
        protected_ids = {
            prerequisite
            for item in normalized
            for prerequisite in (item.get("prerequisites") or [])
            if prerequisite in selected_ids
        }
        missing_lo_ids = {lo.id for lo in lo_by_id.values() if lo.lo_code in missing}
        candidate_evidence: Dict[int, Dict] = {}
        if missing_lo_ids:
            for match in db.query(MatchScore).filter(
                MatchScore.project_version_id == project_version_id,
                MatchScore.lo_id.in_(missing_lo_ids),
                MatchScore.score >= 0.3,
            ).all():
                course = courses.get(int(match.course_id))
                if (
                    not course
                    or course.id in selected_ids
                    or not str(course.course_id or "").startswith("EPVO-")
                    or scope_rank(course) <= 0
                    or not is_project_domain(course)
                ):
                    continue
                lo = lo_by_id.get(match.lo_id)
                if not lo:
                    continue
                evidence = candidate_evidence.setdefault(course.id, {
                    "los": set(), "max": 0.0, "expert": 0.0,
                })
                expert_value = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
                effective_score = max(float(match.score or 0.0), expert_value)
                if effective_score < required_coverage:
                    continue
                evidence["los"].add(lo.lo_code)
                evidence["max"] = max(evidence["max"], effective_score)
                evidence["expert"] = max(
                    evidence["expert"],
                    expert_value,
                )

        real_candidates = sorted(
            (courses[cid] for cid in candidate_evidence),
            key=lambda course: (
                len(candidate_evidence[course.id]["los"]),
                candidate_evidence[course.id]["expert"] > 0,
                candidate_evidence[course.id]["expert"],
                candidate_evidence[course.id]["max"],
                scope_rank(course),
                priority_rank(course),
            ),
            reverse=True,
        )
        for candidate in real_candidates:
            evidence = candidate_evidence[candidate.id]
            still_missing = set(missing) & set(evidence["los"])
            if not still_missing:
                continue
            candidate_credits = int(candidate.credits or 5)
            replaceable = []
            for index, item in enumerate(normalized):
                if (
                    item.get("bridge_module_id") is not None
                    and int(item.get("credits") or 0) == candidate_credits
                ):
                    # A real in-scope course is always preferable to an
                    # unconfirmed bridge that only assumes LO coverage.
                    replaceable.append((-1, False, 0.0, -1, index))
                    continue
                old_course = courses.get(item.get("course_id"))
                if (
                    not old_course
                    or old_course.id in protected_ids
                    or item.get("regulatory_required")
                    or int(item.get("credits") or 0) != candidate_credits
                ):
                    continue
                old_evidence = aggregates.get(old_course.id, {})
                old_supported_missing = len(set(old_evidence.get("lo_codes") or []) & set(missing))
                replaceable.append((
                    old_supported_missing,
                    float(old_evidence.get("expert") or 0.0) > 0,
                    float(old_evidence.get("max") or 0.0),
                    _course_role_rank(old_course, project_domains),
                    index,
                ))
            if not replaceable:
                continue
            replaceable.sort()
            replace_index = replaceable[0][-1]
            normalized[replace_index] = {
                "course_id": candidate.id,
                "title": candidate.title,
                "domain": candidate.domain,
                "credits": candidate_credits,
                "recommended_semester": candidate.recommended_semester,
                "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                "type": candidate.cycle_component or "mandatory",
                "selection_method": "epvo_lo_gap_repair",
                "selection_evidence": {
                    "target_los": sorted(still_missing),
                    "model_score": round(float(evidence["max"]), 4),
                    "epvo_expert_score": round(float(evidence["expert"]), 4),
                },
            }
            selected_ids.add(candidate.id)
            for code in still_missing:
                coverage[code] = max(coverage.get(code, 0.0), float(evidence["max"]))
            missing = [code for code, score in coverage.items() if score < required_coverage]
            if not missing:
                return _unique_items_by_title(normalized)

        if not constraints.get("allow_new_courses", True):
            return _unique_items_by_title(normalized)
        current_bridge_count = sum(1 for item in normalized if item.get("bridge_module_id") is not None)
        slots = max(0, int(constraints.get("max_new_courses", 5)) - current_bridge_count)
        if slots <= 0:
            return normalized
        selected_ids = {item.get("course_id") for item in normalized if item.get("course_id") is not None}
        protected_ids = {
            prerequisite
            for item in normalized
            for prerequisite in (item.get("prerequisites") or [])
            if prerequisite in selected_ids
        }
        replaceable = []
        for index, item in enumerate(normalized):
            course = courses.get(item.get("course_id"))
            if not course or course.id in protected_ids:
                continue
            evidence = aggregates.get(course.id, {})
            replaceable.append((
                _course_role_rank(course, project_domains),
                priority_rank(course),
                float(evidence.get("max") or 0.0),
                int(course.credits or item.get("credits") or 5),
                index,
                item,
            ))
        replaceable.sort(key=lambda row: (row[0], row[1], row[2], -row[3]))
        module_count = min(slots, len(missing), len(replaceable))
        if module_count <= 0:
            return normalized
        total_semesters = int(constraints.get("total_semesters", 8) or 8)
        chunks = [missing[index::module_count] or missing for index in range(module_count)]
        support_by_course: Dict[int, List[str]] = {}
        if selected_course_ids:
            for match in db.query(MatchScore).filter(
                MatchScore.project_version_id == project_version_id,
                MatchScore.course_id.in_(selected_course_ids),
                MatchScore.score >= 0.4,
            ).all():
                lo = lo_by_id.get(match.lo_id)
                if lo:
                    support_by_course.setdefault(int(match.course_id), []).append(lo.lo_code)
        replacement_indexes = []
        modules = []
        for index in range(module_count):
            _role, _priority, _score, credits, item_index, old_item = replaceable[index]
            credits = max(3, int(credits or 3))
            codes = list(dict.fromkeys([
                *chunks[index],
                *support_by_course.get(int(old_item.get("course_id") or 0), []),
            ]))
            code = f"LO_GAP_BRIDGE_{project_version_id}_{variant_type}_{index + 1}"
            title = f"Модуль закрытия пробелов результатов обучения {', '.join(codes)}"
            module = db.query(BridgeModule).filter(
                BridgeModule.project_version_id == project_version_id,
                BridgeModule.course_id == code,
            ).first()
            payload = {
                "title": title,
                "goal": f"Закрыть недостаточно подтверждённые результаты обучения: {', '.join(codes)}.",
                "description": (
                    "Автоматически созданный bridge-модуль заменяет слабую дисциплину, "
                    "когда текущий учебный план не подтверждает один или несколько результатов обучения."
                ),
                "credits": credits,
                "recommended_semester": max(2, min(total_semesters - 1, 3 + index)),
                "learning_outcomes": [
                    f"Демонстрировать достижение результатов обучения {', '.join(codes)} на практическом кейсе.",
                    "Связывать теоретические знания, инструменты и доказательства с требованиями образовательной программы.",
                ],
                "topics": [
                    "Диагностика пробела результата обучения",
                    "Практический кейс и доказательства достижения",
                    "Инструменты, методы и ограничения",
                    "Портфолио результата обучения",
                ],
                "assessment_methods": ["практический кейс", "портфолио", "защита проекта"],
                "target_los": codes,
            }
            if module is None:
                module = BridgeModule(
                    project_version_id=project_version_id,
                    course_id=code,
                    prerequisites=[],
                    source_chunks_json=[],
                    generation_params_json={"mode": "professional_lo_gap_bridge", "variant": variant_type},
                    **payload,
                )
                db.add(module)
            else:
                for key, value in payload.items():
                    setattr(module, key, value)
                module.prerequisites = []
                module.generation_params_json = {"mode": "professional_lo_gap_bridge", "variant": variant_type}
            modules.append(module)
            replacement_indexes.append(item_index)
        db.flush()
        for item_index, module in zip(replacement_indexes, modules):
            normalized[item_index] = _bridge_item(module)
            normalized[item_index]["selection_method"] = "professional_lo_gap_bridge"
        return _unique_items_by_title(normalized)

    def project_domain_index(course: Course) -> int | None:
        mapped = epvo_domain_index.get(course.id)
        if mapped in (0, 1):
            return mapped
        domain = (course.domain or "").lower().strip()
        for index, project_domain in enumerate(project_domains):
            if project_domain and (project_domain in domain or domain in project_domain):
                return index
        return None

    weights = {lo.id: lo.weight or 1.0 for lo in version.learning_outcomes}
    lo_codes_by_id = {lo.id: lo.lo_code for lo in version.learning_outcomes}
    aggregates: Dict[int, Dict] = {}
    for match in db.query(MatchScore).filter(MatchScore.project_version_id == project_version_id).all():
        data = aggregates.setdefault(match.course_id, {
            "sum": 0.0, "los": set(), "lo_codes": set(), "credible_lo_codes": set(),
            "professional_lo_codes": set(), "max": 0.0, "expert": 0.0,
        })
        data["sum"] += match.score * weights.get(match.lo_id, 1.0)
        data["los"].add(match.lo_id)
        if lo_codes_by_id.get(match.lo_id):
            data["lo_codes"].add(lo_codes_by_id[match.lo_id])
        expert_value = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        effective_value = max(float(match.score or 0.0), expert_value)
        lo_code = str(lo_codes_by_id.get(match.lo_id) or "")
        if lo_code and effective_value >= 0.4:
            data["credible_lo_codes"].add(lo_code)
            if not lo_code.startswith("LO-GOSO-"):
                data["professional_lo_codes"].add(lo_code)
        data["expert"] = max(data["expert"], expert_value)
        data["max"] = max(data["max"], effective_value)
    prereq_ids_by_course: Dict[int, List[int]] = {}
    for row in db.execute(course_prerequisites.select()).fetchall():
        prereq_ids_by_course.setdefault(int(row.course_id), []).append(int(row.prerequisite_id))
    eligible_course_ids = set(aggregates)
    if professional_scope:
        frontier = set(eligible_course_ids)
        for _ in range(2):
            next_frontier = {
                prerequisite_id
                for course_id in frontier
                for prerequisite_id in prereq_ids_by_course.get(course_id, [])
                if prerequisite_id not in eligible_course_ids
            }
            eligible_course_ids.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break
        local_prefix = f"AI-CONFIRMED-{project_version_id}-"
        eligible_course_ids.update(
            row[0] for row in db.query(Course.id).filter(Course.course_id.like(f"{local_prefix}%")).all()
        )
        course_query = db.query(Course).filter(Course.id.in_(eligible_course_ids or [-1]))
    else:
        course_query = db.query(Course)
    courses = {
        course.id: course for course in course_query.all()
        if not _is_component_placeholder_title(_title_key(course.title))
    }
    group_codes = [
        str(value or "").strip()
        for value in (constraints.get("group_code"), constraints.get("secondary_group_code"))
        if str(value or "").strip()
    ]
    direction_codes = [
        str(value or "").strip()
        for value in (constraints.get("direction_code"), constraints.get("secondary_direction_code"))
        if str(value or "").strip()
    ]
    primary_group = str(constraints.get("group_code") or "").strip()
    secondary_group = str(constraints.get("secondary_group_code") or "").strip()
    primary_direction = str(constraints.get("direction_code") or "").strip()
    secondary_direction = str(constraints.get("secondary_direction_code") or "").strip()
    epvo_scope = {}
    epvo_priority = {}
    epvo_scope_by_id: Dict[int, int] = {}
    epvo_priority_by_id: Dict[int, int] = {}
    epvo_domain_evidence: Dict[int, List[int]] = {}
    if group_codes or direction_codes:
        scope_conditions = [
            cast(EpvoDisciplineNormalized.group_codes, String).like(f'%"{code}"%')
            for code in group_codes
        ] + [
            cast(EpvoDisciplineNormalized.direction_codes, String).like(f'%"{code}"%')
            for code in direction_codes
        ]
        matched_rows = db.query(EpvoDisciplineNormalized).filter(
            EpvoDisciplineNormalized.approved_course_id.isnot(None),
            EpvoDisciplineNormalized.approved_course_id.in_(list(aggregates) or [-1]),
            or_(*scope_conditions),
        ).all()
        for row in matched_rows:
            row_groups = row.group_codes or []
            row_directions = row.direction_codes or []
            rank_value = (
                3 if any(code in row_groups for code in group_codes)
                else 2 if any(code in row_directions for code in direction_codes)
                else 0
            )
            if rank_value <= 0:
                continue
            source_count = len(row.source_programs or [])
            relevance_value = epvo_row_relevance_score(row, version)
            programme_evidence = aggregates.get(int(row.approved_course_id), {})
            strong_program_evidence = (
                float(programme_evidence.get("max") or 0.0) >= float(settings.COVERAGE_THRESHOLD)
                or float(programme_evidence.get("expert") or 0.0) >= 0.5
            )
            # Exact membership in the selected EPVO group already proves the
            # catalogue scope and education level.  The lightweight row-title
            # relevance heuristic is only a guard for the broader direction
            # fallback; it must not discard a D094/M094/B057 discipline that
            # has a strong project-specific discipline--LO score.
            if relevance_value < 0.52 and rank_value < 3 and not strong_program_evidence:
                continue
            epvo_level_scope_allowed_ids.add(int(row.approved_course_id))
            # Project-specific expert evidence is already present in
            # MatchScore. Avoid aggregating the entire multi-million-link EPVO
            # table for every A/B/C variant merely as a tie-breaker.
            priority_value = int(relevance_value * 1000) + rank_value * 100 + min(source_count, 50) * 5
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
            mapped_course = courses.get(row.approved_course_id)
            if mapped_course:
                epvo_scope_by_id[mapped_course.id] = max(
                    epvo_scope_by_id.get(mapped_course.id, 0), rank_value,
                )
                epvo_priority_by_id[mapped_course.id] = max(
                    epvo_priority_by_id.get(mapped_course.id, 0), priority_value,
                )
                evidence = epvo_domain_evidence.setdefault(mapped_course.id, [0, 0])
                evidence[0] = max(evidence[0], primary_scope)
                evidence[1] = max(evidence[1], secondary_scope)
            for title in (row.title_ru, row.title_kk, row.title_en):
                if title:
                    key = _title_key(title)
                    epvo_scope[key] = max(epvo_scope.get(key, 0), rank_value)
                    epvo_priority[key] = max(epvo_priority.get(key, 0), priority_value)
        for course_id, (primary_score, secondary_score) in epvo_domain_evidence.items():
            if primary_score or secondary_score:
                epvo_domain_index[course_id] = 1 if secondary_score > primary_score else 0

    # In professional EPVO projects an unscored catalogue row cannot pass the
    # evidence guard. Keeping all ~20k repository courses in every repair and
    # quota loop only increases latency. Retain scored candidates, their
    # prerequisite closure, and project-local confirmed replacements.
    if professional_scope:
        prereq_ids_by_course = {
            course_id: [value for value in values if value in eligible_course_ids]
            for course_id, values in prereq_ids_by_course.items()
            if course_id in eligible_course_ids
        }

    def scope_rank(course: Course) -> int:
        return epvo_scope_by_id.get(course.id, epvo_scope.get(_title_key(course.title), 0))
    def priority_rank(course: Course) -> int:
        if course is None:
            return 0
        return epvo_priority_by_id.get(course.id, epvo_priority.get(_title_key(course.title), 0))
    def role_rank(course: Course | None) -> int:
        return _course_role_rank(course, project_domains)

    def admit_real_courses(items: List[Dict]) -> List[Dict]:
        """Final evidence gate shared by every A/B/C selection path.

        Credits and a high rank are not sufficient. Every real non-regulatory
        discipline must have a credible programme LO and pass the selected
        EPVO level/scope. Bridges are kept explicit and are never disguised as
        real-course evidence.
        """
        admitted: List[Dict] = []
        jurisdiction_kz = str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() == "KZ"
        for raw_item in items:
            item = dict(raw_item)
            course_id = item.get("course_id")
            if course_id is None:
                admitted.append(item)
                continue
            course = courses.get(int(course_id))
            if course is None or _is_component_placeholder_title(_title_key(item.get("title") or course.title)):
                continue
            course_code = str(course.course_id or "")
            if course_code.startswith("GOSO-KZ-"):
                if jurisdiction_kz:
                    item["regulatory_required"] = True
                    item["admission_reason"] = "mandatory_goso_kz"
                    admitted.append(item)
                continue
            if not _education_level_course_allowed(course, constraints.get("education_level")):
                continue
            evidence = aggregates.get(course.id, {})
            # Generic GSOS outcomes justify only explicit GOSO courses.
            # An ordinary EPVO elective must support at least one programme-
            # specific professional outcome.
            credible_los = set(evidence.get("professional_lo_codes") or set())
            if not credible_los:
                continue
            if course_code.startswith("EPVO-") and scope_rank(course) <= 0:
                continue
            if not is_project_domain(course):
                continue
            item["admission_reason"] = (
                "epvo_scope_and_lo"
                if scope_rank(course) > 0 or course_code.startswith("EPVO-")
                else "local_course_and_lo"
            )
            item["admission_los"] = sorted(credible_los)
            item["admission_score"] = round(float(evidence.get("max") or 0.0), 4)
            admitted.append(item)
        return _unique_items_by_title(admitted)

    raw_prereq_ids_by_course = prereq_ids_by_course
    generic_prerequisite_terms = {
        "основ", "введен", "систем", "метод", "технолог", "управлен", "анализ",
        "соврем", "дисциплин", "course", "system", "method", "technology", "management",
    }

    def prerequisite_title_stems(course: Course) -> set[str]:
        return {
            token[:7]
            for token in re.findall(r"[\w]+", _title_key(course.title), flags=re.UNICODE)
            if len(token) >= 5 and not any(token.startswith(value) for value in generic_prerequisite_terms)
        }

    # The repository contains historical and automatically inferred edges.
    # For generation, retain only an earlier prerequisite that is supported by
    # this programme's LO evidence or by a clear subject-title relationship.
    filtered_prerequisites: Dict[int, List[int]] = {}
    for course_id, prerequisite_ids in raw_prereq_ids_by_course.items():
        course = courses.get(course_id)
        if not course:
            continue
        course_stems = prerequisite_title_stems(course)
        for prerequisite_id in prerequisite_ids:
            prerequisite = courses.get(prerequisite_id)
            if not prerequisite:
                continue
            if int(prerequisite.recommended_semester or 1) >= int(course.recommended_semester or 1):
                continue
            evidence_score = float(aggregates.get(prerequisite_id, {}).get("max") or 0.0)
            shared_stems = course_stems & prerequisite_title_stems(prerequisite)
            if evidence_score < 0.25 and len(shared_stems) < 2:
                continue
            filtered_prerequisites.setdefault(course_id, []).append(prerequisite_id)
    prereq_ids_by_course = filtered_prerequisites

    num_semesters = int(constraints.get("total_semesters", 8))
    depth_cache = {}
    def course_depth(cid, path=None):
        if cid in depth_cache: return depth_cache[cid]
        path = path or set()
        if cid in path or cid not in courses: return num_semesters + 1
        prereqs = prereq_ids_by_course.get(cid, [])
        value = 0 if not prereqs else 1 + max(course_depth(pre_id, path | {cid}) for pre_id in prereqs)
        depth_cache[cid] = value
        return value
    def rank(cid):
        data, course = aggregates[cid], courses.get(cid)
        credits = max(1, course.credits if course else 1)
        if variant_type == "B":
            # Reuse-first variant: prefer scoped existing courses with a simple
            # prerequisite chain, but avoid overloading early semesters with
            # several large 8-9 credit foundations.
            return (
                role_rank(course),
                scope_rank(course),
                priority_rank(course),
                -(course.recommended_semester or 99),
                -course_depth(cid),
                -len(prereq_ids_by_course.get(cid, [])),
                data["max"],
                -credits,
                course.id,
            )
        if variant_type == "C":
            domains = {(version.project.domain1 or "").lower(), (version.project.domain2 or "").lower()}
            domain_bonus = 1 if course and any(d and (d in (course.domain or "").lower() or (course.domain or "").lower() in d) for d in domains) else 0
            return (role_rank(course), scope_rank(course), priority_rank(course), -len(prereq_ids_by_course.get(cid, [])), domain_bonus, data["sum"] / credits, -course_depth(cid), -course.id)
        return (role_rank(course), scope_rank(course), priority_rank(course), len(data["los"]), data["sum"], data["max"], -course_depth(cid), -course.id)
    candidate_ids = sorted(
        (cid for cid in aggregates if cid in courses and is_project_domain(courses[cid]) and course_depth(cid) < num_semesters),
        key=rank,
        reverse=True,
    )
    # Seed data and imported catalogues may contain several rows for the same
    # discipline.  They are alternatives, not separate curriculum subjects.
    unique_candidate_ids = []
    seen_candidate_titles = set()
    for cid in candidate_ids:
        title = _title_key(courses[cid].title)
        if title in seen_candidate_titles:
            continue
        seen_candidate_titles.add(title)
        unique_candidate_ids.append(cid)
    candidate_ids = unique_candidate_ids
    root_credits = sum(
        int(course.credits or 5)
        for course in courses.values()
        if is_project_domain(course) and course_depth(course.id) == 0
    )
    foundation_reserve = min(
        max(0, int(constraints.get("max_credits_per_semester", 30)) - root_credits),
        int(constraints.get("max_new_courses", 5)) * 7,
    )
    target = max(0, target - foundation_reserve)
    maximum = target if foundation_reserve else target + max(0, int(constraints.get("credit_tolerance", TOTAL_CREDIT_TOLERANCE)))
    optimizer_cache_key = f"nsga2_variants:{project_version_id}"
    if optimizer_cache_key not in db.info:
        # Interdisciplinary programmes are intentionally handled by the
        # deterministic hard-quota path below.  The previous implementation
        # still ran the full NSGA-II search and then discarded its result,
        # repeating hundreds of millions of operations for no plan benefit.
        if interdisciplinary:
            db.info[optimizer_cache_key] = {}
        else:
            from app.planner.nsga2 import optimize_variants
            domain_catalog_size = sum(1 for course in courses.values() if is_project_domain(course))
            large_catalog = domain_catalog_size >= 1200
            optimizer_seed_ids = candidate_ids[:350] if large_catalog else candidate_ids
            if large_catalog:
                db.info[optimizer_cache_key] = {}
            else:
                db.info[optimizer_cache_key] = optimize_variants(
                    version=version,
                    db=db,
                    seed_course_ids=optimizer_seed_ids,
                    target_credits=target,
                    maximum_credits=maximum,
                    population_size=settings.NSGA2_POPULATION,
                    generations=settings.NSGA2_GENERATIONS,
                    crossover_probability=settings.NSGA2_CROSSOVER_PROBABILITY,
                    mutation_probability=settings.NSGA2_MUTATION_PROBABILITY,
                )
    # Interdisciplinary programmes use the deterministic hard-quota path.
    # The unconstrained NSGA-II seed can violate per-domain minima and should
    # remain an experiment for standard one-domain programmes only.
    optimized = db.info[optimizer_cache_key].get(variant_type)
    if optimized:
        quality_bridge = db.query(BridgeModule).filter(
            BridgeModule.project_version_id == project_version_id,
            BridgeModule.course_id == f"QUALITY_BRIDGE_{project_version_id}",
        ).first()
        if interdisciplinary and quality_bridge and not any(item.get("bridge_module_id") for item in optimized):
            protected_ids = {
                prerequisite_id
                for item in optimized
                for prerequisite_id in (item.get("prerequisites") or [])
            }
            replaceable = [
                (index, item)
                for index, item in enumerate(optimized)
                if item.get("course_id") not in protected_ids
                and int(item.get("credits") or 0) == int(quality_bridge.credits or 0)
            ]
            if replaceable:
                # Keep all variants interdisciplinary while retaining a
                # deterministic distinction between their course sets.
                offset = {"A": 0, "B": 1, "C": 2}.get(variant_type, 0)
                replace_index, _ = replaceable[offset % len(replaceable)]
                optimized = [dict(item) for item in optimized]
                optimized[replace_index] = {
                    "bridge_module_id": quality_bridge.id,
                    "title": quality_bridge.title,
                    "domain": "interdisciplinary",
                    "credits": quality_bridge.credits or 5,
                    "recommended_semester": quality_bridge.recommended_semester,
                    "prerequisites": quality_bridge.prerequisites or [],
                    "type": "bridge",
                }
        for bridge in [core_bridge, *secondary_bridges]:
            optimized = _force_bridge_item(optimized, bridge, variant_type)
        optimized = _promote_epvo_priority_courses(optimized, courses, prereq_ids_by_course, is_project_domain, course_depth, num_semesters, priority_rank, target, maximum)
        optimized = _limit_general_course_items(
            optimized,
            courses,
            project_domains,
            target,
            max_general_percent,
        )
        optimized = _trim_to_target_credits(close_professional_lo_gaps(top_up_with_credit_bridges(remove_weak_general_items(optimized))), target, db)
        optimized = _diversify_variant_items(optimized, version, db, variant_type)
        optimized = _trim_to_target_credits(close_professional_lo_gaps(top_up_with_credit_bridges(remove_weak_general_items(optimized))), target, db)
        # The optimized path used to return before the common evidence gate.
        # build_curriculum_plan then removed every real course because the
        # required admission_los/admission_score fields were absent and filled
        # the resulting gap with bridges.  Apply the same final contract as
        # the deterministic path before returning an NSGA-II variant.
        optimized = admit_real_courses(optimized)
        optimized = close_professional_lo_gaps(optimized)
        optimized = admit_real_courses(optimized)
        optimized = top_up_with_credit_bridges(optimized)
        optimized = _trim_to_target_credits(optimized, target, db)
        return _unique_items_by_title(optimized)
    selected: Dict[int, Dict] = {}
    def bundle(cid, visiting=None):
        visiting = visiting or set()
        if cid in visiting or cid in selected or cid not in courses: return []
        # A domain course can reference a generic prerequisite in the repository.
        # Do not silently pull that foreign-domain prerequisite into this project;
        # reject the whole bundle and let the bridge-module fallback close the gap.
        if not is_project_domain(courses[cid]):
            return []
        result = []
        for pre_id in prereq_ids_by_course.get(cid, []):
            prerequisite_bundle = bundle(pre_id, visiting | {cid})
            if pre_id not in selected and not prerequisite_bundle:
                return []
            result.extend(prerequisite_bundle)
        if cid not in selected and all(item["course_id"] != cid for item in result):
            c = courses[cid]; result.append({"course_id": c.id, "title": c.title, "domain": c.domain, "credits": c.credits or 5, "recommended_semester": c.recommended_semester, "prerequisites": prereq_ids_by_course.get(c.id, []), "type": c.cycle_component or "mandatory"})
        return result
    total = 0
    foundation_target = max(0, int(constraints.get("max_credits_per_semester", target / max(num_semesters, 1))) - 3)
    foundation_ids = sorted(
        (cid for cid in courses if is_project_domain(courses[cid]) and course_depth(cid) == 0),
        key=lambda cid: tuple(rank(cid)) if cid in aggregates else (0, 0, 0),
        reverse=True,
    )
    for cid in foundation_ids:
        foundation_bundle = bundle(cid)
        item = foundation_bundle[-1] if foundation_bundle else None
        if not item or total + item["credits"] > maximum: continue
        selected[cid] = item; total += item["credits"]
        if total >= foundation_target: break

    def selected_domain_credits(domain_index: int) -> int:
        value = 0
        for item in selected.values():
            course = courses.get(item.get("course_id"))
            if course and project_domain_index(course) == domain_index:
                value += int(item.get("credits") or 0)
        return value

    domain_quota_candidate_cache: Dict[int, List[Course]] = {}

    def domain_quota_candidates(domain_index: int) -> List[Course]:
        cached = domain_quota_candidate_cache.get(domain_index)
        if cached is not None:
            return cached
        cached = sorted(
            (
                course for course in courses.values()
                if is_project_domain(course)
                and project_domain_index(course) == domain_index
                and course_depth(course.id) < num_semesters
            ),
            key=lambda course: (
                -role_rank(course),
                -scope_rank(course),
                -priority_rank(course),
                course.recommended_semester or 99,
                course.id,
            ),
        )
        domain_quota_candidate_cache[domain_index] = cached
        return cached

    def rebalance_domain_quotas(items: List[Dict]) -> List[Dict]:
        if not interdisciplinary:
            return items
        domain_quota_tolerance = max(
            0.0, float(constraints.get("domain_quota_tolerance_credits", 3) or 0)
        )
        required = [
            max(
                0.0,
                math.ceil(
                    max(
                        0,
                        int(constraints.get("total_credits", quota_total_credits) or quota_total_credits)
                        - sum(
                            int(item.get("credits") or 0)
                            for item in items
                            if item.get("regulatory_required")
                        ),
                    )
                    * min_domain_percent[index]
                    / 100
                )
                - domain_quota_tolerance,
            )
            for index in range(2)
        ]
        if not any(required):
            return items
        normalized = [dict(item) for item in items]

        secondary_bridge_ids = {bridge.id for bridge in secondary_bridges}
        core_bridge_id = core_bridge.id if core_bridge is not None else None
        domain_bridge_codes = {
            bridge.id: str(bridge.course_id or "")
            for bridge in [*(secondary_bridges or []), *([core_bridge] if core_bridge is not None else [])]
        }
        bridge_ids_in_plan = {
            int(item.get("bridge_module_id"))
            for item in normalized
            if item.get("bridge_module_id") is not None
        }
        if bridge_ids_in_plan:
            domain_bridge_codes.update({
                bridge.id: str(bridge.course_id or "")
                for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids_in_plan)).all()
            })

        def credits_by_domain() -> List[float]:
            values = [0.0, 0.0]
            for item in normalized:
                course = courses.get(item.get("course_id"))
                index = project_domain_index(course) if course else None
                if index in (0, 1):
                    values[index] += int(item.get("credits") or 0)
                    continue
                bridge_id = item.get("bridge_module_id")
                credits = float(item.get("credits") or 0)
                if bridge_id in secondary_bridge_ids:
                    values[1] += credits
                elif bridge_id == core_bridge_id or str(domain_bridge_codes.get(bridge_id) or "").startswith(("AUTO_BRIDGE_", "QUALITY_BRIDGE_")):
                    values[0] += credits / 2.0
                    values[1] += credits / 2.0
            return values

        def selected_ids() -> set:
            return {item.get("course_id") for item in normalized if item.get("course_id") is not None}

        def protected_ids() -> set:
            ids = selected_ids()
            prerequisite_ids = {
                prerequisite_id
                for item in normalized
                for prerequisite_id in (item.get("prerequisites") or [])
                if prerequisite_id in ids
            }
            expert_confirmed_ids = {
                int(course_id)
                for mapping_name in ("confirmed_bridge_replacements", "confirmed_course_replacements")
                for course_id in (constraints.get(mapping_name) or {}).values()
                if str(course_id).isdigit()
            }
            return prerequisite_ids | expert_confirmed_ids

        for domain_index in (0, 1):
            guard = 0
            # A 40% quota may require more than twenty 3-credit swaps. Stop
            # only after the plan-sized safety limit or when no valid swap is
            # available, not at an arbitrary fixed count.
            guard_limit = max(20, len(normalized) * 2)
            while credits_by_domain()[domain_index] < required[domain_index] and guard < guard_limit:
                guard += 1
                current = credits_by_domain()
                ids = selected_ids()
                titles = {_title_key(item.get("title")) for item in normalized if item.get("title")}
                candidates = [
                    course for course in domain_quota_candidates(domain_index)
                    if course.id not in ids
                    and _title_key(course.title) not in titles
                    and all(pre_id in ids for pre_id in prereq_ids_by_course.get(course.id, []))
                ][:80]
                swapped = False
                protected = protected_ids()
                for candidate in candidates:
                    candidate_credits = int(candidate.credits or 5)
                    replaceable = []
                    for index, item in enumerate(normalized):
                        course = courses.get(item.get("course_id"))
                        replace_domain = project_domain_index(course) if course else None
                        can_reduce_replace_domain = (
                            replace_domain not in (0, 1)
                            or current[replace_domain] - candidate_credits >= required[replace_domain]
                        )
                        if (
                            course
                            and not item.get("regulatory_required")
                            and item.get("course_id") not in protected
                            and replace_domain != domain_index
                            and int(item.get("credits") or 0) == candidate_credits
                            and can_reduce_replace_domain
                        ):
                            replaceable.append((index, item, course))
                    if not replaceable:
                        continue
                    replaceable.sort(
                        key=lambda row: (
                            _course_role_rank(row[2], project_domains),
                            priority_rank(row[2]),
                            int(row[1].get("recommended_semester") or 99),
                        )
                    )
                    replace_index, _old_item, _old_course = replaceable[0]
                    normalized[replace_index] = {
                        "course_id": candidate.id,
                        "title": candidate.title,
                        "domain": candidate.domain,
                        "credits": candidate.credits or 5,
                        "recommended_semester": candidate.recommended_semester,
                        "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                        "type": candidate.cycle_component or "mandatory",
                        "selection_method": "domain_quota_rebalance",
                    }
                    swapped = True
                    break
                if not swapped:
                    # Credit values in EPVO are heterogeneous (3/4/5). A
                    # strict one-for-one swap can stop below quota even when
                    # enough strong courses exist. Try bounded 1–2 course
                    # exchanges with exactly the same total credits.
                    replaceable_all = []
                    for index, item in enumerate(normalized):
                        course = courses.get(item.get("course_id"))
                        replace_domain = project_domain_index(course) if course else None
                        if (
                            course
                            and not item.get("regulatory_required")
                            and item.get("course_id") not in protected
                            and replace_domain != domain_index
                        ):
                            replaceable_all.append((index, item, course))
                    replacement_groups: Dict[int, List[tuple]] = {}
                    for size in (1, 2):
                        for group in combinations(replaceable_all, size):
                            group_credits = sum(int(row[1].get("credits") or 0) for row in group)
                            other_domain = project_domain_index(group[0][2])
                            if (
                                other_domain not in (0, 1)
                                or current[other_domain] - group_credits >= required[other_domain]
                            ):
                                replacement_groups.setdefault(group_credits, []).append(group)
                    candidate_groups = [*( (course,) for course in candidates )]
                    candidate_groups.extend(combinations(candidates[:40], 2))
                    for candidate_group in candidate_groups:
                        group_credits = sum(int(course.credits or 5) for course in candidate_group)
                        replacements = replacement_groups.get(group_credits)
                        if not replacements:
                            continue
                        replacement_group = min(
                            replacements,
                            key=lambda group: sum(
                                _course_role_rank(row[2], project_domains) * 1000
                                + priority_rank(row[2])
                                for row in group
                            ),
                        )
                        for replace_index, _item, _course in sorted(
                            replacement_group, key=lambda row: row[0], reverse=True
                        ):
                            normalized.pop(replace_index)
                        for candidate in candidate_group:
                            normalized.append({
                                "course_id": candidate.id,
                                "title": candidate.title,
                                "domain": candidate.domain,
                                "credits": candidate.credits or 5,
                                "recommended_semester": candidate.recommended_semester,
                                "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                                "type": candidate.cycle_component or "mandatory",
                                "selection_method": "domain_quota_group_rebalance",
                            })
                        swapped = True
                        break
                if not swapped:
                    def missing_domain_bundle(course_id: int, visiting: set | None = None):
                        visiting = visiting or set()
                        if course_id in ids:
                            return []
                        if course_id in visiting:
                            return None
                        course = courses.get(course_id)
                        if (
                            course is None
                            or (
                                course.id not in epvo_domain_index
                                and not _course_domain_matches(course, project_domains)
                            )
                        ):
                            return None
                        mapped_domain = project_domain_index(course)
                        if mapped_domain != domain_index:
                            foundation_title = _title_key(course.title)
                            foundation_tokens = (
                                "алгоритм", "algorithm", "нейрон", "neural",
                                "данн", "data", "статист", "statistic",
                                "программ", "program", "информ", "comput",
                                "математ", "math", "биоинформ", "bioinform",
                            )
                            if not any(token in foundation_title for token in foundation_tokens):
                                return None
                        bundle_courses: List[Course] = []
                        for prerequisite_id in prereq_ids_by_course.get(course_id, []):
                            prerequisite_bundle = missing_domain_bundle(
                                prerequisite_id, visiting | {course_id}
                            )
                            if prerequisite_bundle is None:
                                return None
                            bundle_courses.extend(prerequisite_bundle)
                        bundle_courses.append(course)
                        return list({value.id: value for value in bundle_courses}.values())

                    bundle_candidates = []
                    for candidate in domain_quota_candidates(domain_index):
                        if candidate.id in ids or _title_key(candidate.title) in titles:
                            continue
                        candidate_bundle = missing_domain_bundle(candidate.id)
                        if not candidate_bundle or len(candidate_bundle) > 4:
                            continue
                        bundle_credits = sum(int(value.credits or 5) for value in candidate_bundle)
                        target_credits = sum(
                            int(value.credits or 5)
                            for value in candidate_bundle
                            if project_domain_index(value) == domain_index
                        )
                        if bundle_credits <= 0 or bundle_credits > 24 or target_credits <= 0:
                            continue
                        bundle_candidates.append((candidate_bundle, bundle_credits, target_credits))
                        if len(bundle_candidates) >= 80:
                            break

                    replaceable_all = []
                    for index, item in enumerate(normalized):
                        course = courses.get(item.get("course_id"))
                        replace_domain = project_domain_index(course) if course else None
                        if (
                            course
                            and not item.get("regulatory_required")
                            and item.get("course_id") not in protected
                            and replace_domain != domain_index
                        ):
                            replaceable_all.append((index, item, course))
                    replaceable_all.sort(key=lambda row: (
                        _course_role_rank(row[2], project_domains),
                        priority_rank(row[2]),
                        int(row[1].get("recommended_semester") or 99),
                    ))
                    replaceable_all = replaceable_all[:24]
                    replacement_groups = {}
                    for size in (1, 2, 3, 4):
                        for group in combinations(replaceable_all, size):
                            group_credits = sum(int(row[1].get("credits") or 0) for row in group)
                            other_domain = project_domain_index(group[0][2])
                            if (
                                other_domain not in (0, 1)
                                or current[other_domain] - group_credits >= required[other_domain]
                            ):
                                replacement_groups.setdefault(group_credits, group)
                    for candidate_bundle, bundle_credits, target_credits in bundle_candidates:
                        replacement_group = replacement_groups.get(bundle_credits)
                        if not replacement_group:
                            continue
                        for replace_index, _item, _course in sorted(
                            replacement_group, key=lambda row: row[0], reverse=True
                        ):
                            normalized.pop(replace_index)
                        for candidate in candidate_bundle:
                            normalized.append({
                                "course_id": candidate.id,
                                "title": candidate.title,
                                "domain": candidate.domain,
                                "credits": candidate.credits or 5,
                                "recommended_semester": candidate.recommended_semester,
                                "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                                "type": candidate.cycle_component or "mandatory",
                                "selection_method": "domain_quota_prerequisite_bundle",
                            })
                        swapped = True
                        break
                if not swapped:
                    break
        return normalized

    def replace_redundant_bridges_with_real_courses(items: List[Dict], protected_bridge_ids: set[int] | None = None) -> List[Dict]:
        """Replace a bridge only when its LO role is already supported by real courses.

        This prevents historical/forced bridge modules from surviving after a
        later EPVO repository expansion has supplied suitable real courses.
        Credit equality keeps the plan envelope unchanged.
        """
        normalized = [dict(item) for item in items]
        protected_bridge_ids = protected_bridge_ids or set()
        bridge_ids = {
            int(item.get("bridge_module_id"))
            for item in normalized
            if item.get("bridge_module_id") is not None
        } - protected_bridge_ids
        if not bridge_ids:
            return normalized
        bridge_by_id = {
            bridge.id: bridge
            for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids)).all()
        }
        selected_real_ids = {
            int(item["course_id"])
            for item in normalized
            if item.get("course_id") is not None
        }
        covered_codes = set()
        for course_id in selected_real_ids:
            evidence = aggregates.get(course_id, {})
            if float(evidence.get("max") or 0.0) >= float(settings.COVERAGE_THRESHOLD):
                covered_codes.update(evidence.get("lo_codes") or set())

        candidates = [
            course for course in courses.values()
            if course.id not in selected_real_ids
            and is_project_domain(course)
            and scope_rank(course) >= 2
            and _course_curriculum_role(course, project_domains) != "general"
            and all(
                prerequisite_id in selected_real_ids
                for prerequisite_id in prereq_ids_by_course.get(course.id, [])
            )
            and float(aggregates.get(course.id, {}).get("max") or 0.0) >= 0.4
        ]
        used = set(selected_real_ids)
        for index, item in enumerate(normalized):
            bridge_id = item.get("bridge_module_id")
            if bridge_id is None or int(bridge_id) in protected_bridge_ids:
                continue
            bridge = bridge_by_id.get(int(bridge_id))
            if not bridge:
                continue
            target_codes = set(bridge.target_los or [])
            if target_codes and not target_codes.issubset(covered_codes):
                continue
            same_credit = [
                course for course in candidates
                if course.id not in used and int(course.credits or 5) == int(item.get("credits") or 5)
            ]
            if not same_credit:
                continue
            same_credit.sort(
                key=lambda course: (
                    len(set(aggregates.get(course.id, {}).get("lo_codes") or set()) & target_codes),
                    float(aggregates.get(course.id, {}).get("expert") or 0.0),
                    float(aggregates.get(course.id, {}).get("max") or 0.0),
                    priority_rank(course),
                ),
                reverse=True,
            )
            replacement = same_credit[0]
            used.add(replacement.id)
            normalized[index] = {
                "course_id": replacement.id,
                "title": replacement.title,
                "domain": replacement.domain,
                "credits": int(item.get("credits") or replacement.credits or 5),
                "recommended_semester": replacement.recommended_semester,
                "prerequisites": [],
                "type": replacement.cycle_component or "elective",
                "selection_method": "redundant_bridge_replaced_by_epvo",
            }
        return normalized

    def fill_domain_quota(domain_index: int) -> None:
        nonlocal total
        regulatory_selected_credits = sum(
            int(item.get("credits") or 0)
            for item in selected.values()
            if item.get("regulatory_required")
        )
        quota_base = max(0, quota_total_credits - regulatory_selected_credits)
        required = math.ceil(quota_base * min_domain_percent[domain_index] / 100)
        if required <= 0:
            return
        domain_candidates = [
            cid for cid in candidate_ids
            if cid in courses and project_domain_index(courses[cid]) == domain_index
        ]
        for cid in domain_candidates:
            if selected_domain_credits(domain_index) >= required:
                break
            additions = list({
                item["course_id"]: item
                for item in bundle(cid)
                if item["course_id"] not in selected
            }.values())
            addition_credits = sum(item["credits"] for item in additions)
            if not additions or total + addition_credits > maximum:
                continue
            for item in additions:
                selected[item["course_id"]] = item
            total = sum(item["credits"] for item in selected.values())

    # Respect the quotas entered in the project wizard before the generic fill.
    if interdisciplinary:
        fill_domain_quota(1)
    fill_domain_quota(0)

    for cid in candidate_ids:
        additions = list({item["course_id"]: item for item in bundle(cid) if item["course_id"] not in selected}.values())
        addition_credits = sum(item["credits"] for item in additions)
        if total + addition_credits > maximum: continue
        for item in additions: selected[item["course_id"]] = item
        total = sum(item["credits"] for item in selected.values())
        if total >= target: break
    if total < target:
        if variant_type == "B":
            fallback = sorted((c for c in courses.values() if is_project_domain(c) and course_depth(c.id) < num_semesters), key=lambda c: (-role_rank(c), -scope_rank(c), c.recommended_semester or 99, c.credits or 5, c.id))
        elif variant_type == "C":
            fallback = sorted((c for c in courses.values() if is_project_domain(c) and course_depth(c.id) < num_semesters), key=lambda c: (-role_rank(c), -scope_rank(c), (c.domain or "").lower(), c.recommended_semester or 99, -c.id))
        else:
            fallback = sorted((c for c in courses.values() if is_project_domain(c) and course_depth(c.id) < num_semesters), key=lambda c: (-role_rank(c), -scope_rank(c), c.recommended_semester or 99, c.credits or 5, c.id))
        for course in fallback:
            additions = list({item["course_id"]: item for item in bundle(course.id) if item["course_id"] not in selected}.values())
            addition_credits = sum(item["credits"] for item in additions)
            if additions and total + addition_credits <= maximum:
                for item in additions: selected[item["course_id"]] = item
                total = sum(item["credits"] for item in selected.values())
                if total >= target: break
    result = _limit_general_course_items(
        list(selected.values()),
        courses,
        project_domains,
        target,
        max_general_percent,
    )
    result = _trim_to_target_credits(close_professional_lo_gaps(top_up_with_credit_bridges(remove_weak_general_items(result))), target, db)
    for bridge in [core_bridge, *secondary_bridges]:
        result = _force_bridge_item(result, bridge, variant_type)
    total = sum(int(item.get("credits") or 0) for item in result)
    if constraints.get("allow_new_courses", True):
        existing_bridge_count = sum(1 for item in result if item.get("bridge_module_id") is not None)
        configured_max_new_courses = int(constraints.get("max_new_courses", 5))
        max_new_courses = max(configured_max_new_courses, existing_bridge_count + math.ceil(max(0, target - total) / 7))
        auto_prefix = f"AUTO_BRIDGE_{project_version_id}_"
        expert_bridges = db.query(BridgeModule).filter(
            BridgeModule.project_version_id == project_version_id,
            ~BridgeModule.course_id.like(f"{auto_prefix}%"),
        ).order_by(BridgeModule.id.desc()).all()
        expert_bridges.sort(key=lambda module: (-(module.credits or 5), -module.id))
        seen_bridge_titles = {
            " ".join((item.get("title") or "").lower().split())
            for item in result
            if item.get("bridge_module_id") is not None
        }
        for bm in expert_bridges:
            normalized_title = " ".join((bm.title or "").lower().split())
            if not normalized_title or normalized_title in seen_bridge_titles:
                continue
            credits = bm.credits or 5
            slots_after = max_new_courses - existing_bridge_count - 1
            credits_still_needed = max(0, target - (total + credits))
            # Reserve enough slots for deterministic 7-credit bridge modules;
            # otherwise several small/duplicate AI suggestions can leave the
            # curriculum below its mandatory credit target.
            if credits_still_needed > slots_after * 7:
                continue
            if total + credits <= maximum:
                bridge = _bridge_item(bm)
                bridge["credits"] = credits
                bridge["type"] = "mandatory"
                result.append(bridge)
                total += credits
                existing_bridge_count += 1
                seen_bridge_titles.add(normalized_title)
            if total >= target: break
        remaining_slots = max(0, max_new_courses - existing_bridge_count)
        if total < target and remaining_slots > 0:
            needed = min(maximum - total, target - total)
            desired_count = remaining_slots if variant_type == "C" else None
            auto_modules = ensure_credit_bridge_modules(
                version,
                db,
                needed,
                remaining_slots,
                desired_count=desired_count,
            )
            for bm in auto_modules:
                credits = bm.credits or 5
                if total + credits > maximum:
                    continue
                bridge = _bridge_item(bm)
                bridge["credits"] = credits
                result.append(bridge)
                total += credits
                if total >= target:
                    break
    if variant_type == "B":
        # Some legacy projects have many equal 5-credit candidates.  In that
        # case the "reuse-first" B heuristic can converge to the same final
        # set as A even when the ordering differs.  Swap a few safe electives
        # for same-credit alternatives from the same project domains so B is a
        # genuine alternative without breaking prerequisites or credits.
        selected_ids = {
            item.get("course_id")
            for item in result
            if item.get("course_id") is not None
        }
        protected_ids = {
            prerequisite_id
            for item in result
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in selected_ids
        }
        alternatives_by_credit: Dict[int, List[Course]] = {}
        for course in courses.values():
            if (
                course.id not in selected_ids
                and is_project_domain(course)
                and course_depth(course.id) < num_semesters
                and not prereq_ids_by_course.get(course.id)
            ):
                alternatives_by_credit.setdefault(int(course.credits or 5), []).append(course)
        for alternatives in alternatives_by_credit.values():
            alternatives.sort(key=lambda course: course.id, reverse=True)
        removable = [
            (index, item)
            for index, item in enumerate(result)
            if item.get("course_id") is not None
            and item.get("course_id") not in protected_ids
        ]
        removable.sort(key=lambda pair: int(pair[1].get("course_id") or 0))
        swaps = 0
        for index, item in removable:
            if swaps >= 4:
                break
            credits = int(item.get("credits") or 5)
            alternative = None
            while alternatives_by_credit.get(credits):
                candidate = alternatives_by_credit[credits].pop(0)
                if candidate.id not in selected_ids:
                    alternative = candidate
                    break
            if alternative is None:
                continue
            selected_ids.discard(item.get("course_id"))
            selected_ids.add(alternative.id)
            result[index] = {
                "course_id": alternative.id,
                "title": alternative.title,
                "domain": alternative.domain,
                "credits": alternative.credits or 5,
                "recommended_semester": alternative.recommended_semester,
                "prerequisites": [],
                "type": alternative.cycle_component or "mandatory",
            }
            swaps += 1
    result = _promote_epvo_priority_courses(result, courses, prereq_ids_by_course, is_project_domain, course_depth, num_semesters, priority_rank, target, maximum)
    result = _limit_general_course_items(
        result,
        courses,
        project_domains,
        target,
        max_general_percent,
    )
    result = rebalance_domain_quotas(result)
    result = _diversify_variant_items(result, version, db, variant_type)
    result = _trim_to_target_credits(close_professional_lo_gaps(top_up_with_credit_bridges(remove_weak_general_items(result))), target, db)
    result = _limit_general_course_items(
        result,
        courses,
        project_domains,
        target,
        max_general_percent,
    )
    result = _promote_epvo_priority_courses(
        result,
        courses,
        prereq_ids_by_course,
        lambda course: is_project_domain(course)
        and _course_curriculum_role(course, project_domains) != "general",
        course_depth,
        num_semesters,
        priority_rank,
        target,
        maximum,
    )
    result = _trim_to_target_credits(top_up_with_credit_bridges(result), target, db)
    result = rebalance_domain_quotas(result)
    confirmed_course_replacements = {
        int(course_id): int(replacement_id)
        for course_id, replacement_id in (constraints.get("confirmed_course_replacements") or {}).items()
        if str(course_id).isdigit() and str(replacement_id).isdigit()
    }
    if confirmed_course_replacements:
        selected_ids = {int(item.get("course_id")) for item in result if item.get("course_id")}
        for index, item in enumerate(result):
            old_id = int(item.get("course_id") or 0)
            replacement_id = confirmed_course_replacements.get(old_id)
            replacement = courses.get(replacement_id)
            if not replacement or replacement_id in selected_ids:
                continue
            selected_ids.discard(old_id)
            selected_ids.add(replacement_id)
            result[index] = {
                "course_id": replacement.id,
                "title": replacement.title,
                "domain": replacement.domain,
                "credits": int(item.get("credits") or replacement.credits or 5),
                "recommended_semester": int(item.get("recommended_semester") or replacement.recommended_semester or 1),
                "latest_semester": int(item.get("latest_semester") or num_semesters),
                "prerequisites": prereq_ids_by_course.get(replacement.id, []),
                "type": replacement.cycle_component or item.get("type") or "elective",
                "selection_method": "expert_confirmed_course_replacement",
            }
    confirmed_replacements = {
        int(bridge_id): int(course_id)
        for bridge_id, course_id in (constraints.get("confirmed_bridge_replacements") or {}).items()
        if str(bridge_id).isdigit() and str(course_id).isdigit()
    }
    result = replace_redundant_bridges_with_real_courses(result, set(confirmed_replacements))
    result = rebalance_domain_quotas(result)
    if confirmed_replacements:
        for index, item in enumerate(result):
            course_id = confirmed_replacements.get(int(item.get("bridge_module_id") or 0))
            course = courses.get(course_id)
            if not course:
                continue
            result[index] = {
                "course_id": course.id,
                "title": course.title,
                "domain": course.domain,
                # Expert confirmation replaces the bridge content/name but
                # preserves the curriculum credit envelope and semester slot.
                "credits": int(item.get("credits") or course.credits or 5),
                "recommended_semester": int(item.get("recommended_semester") or course.recommended_semester or 1),
                "latest_semester": int(item.get("latest_semester") or num_semesters),
                "prerequisites": prereq_ids_by_course.get(course.id, []),
                "type": course.cycle_component or "mandatory",
                "selection_method": "expert_confirmed_ai_bridge_replacement",
            }
    # Expert replacements are applied late and can change the domain envelope.
    # Recheck quotas once more while keeping those confirmed courses protected.
    result = rebalance_domain_quotas(result)
    # Quota repair and variant diversification may remove the only real source
    # of an LO. Close those gaps again at the true end of selection, then
    # restore quotas once more; bridges never count as real LO evidence here.
    result = close_professional_lo_gaps(result)
    result = rebalance_domain_quotas(result)
    result = close_professional_lo_gaps(result)
    # Run diversification after all priority-promotion passes.  Previously B
    # was diversified earlier and then the final EPVO promotion restored the
    # same courses as A.  Recheck hard quotas and LO gaps after the late swap.
    if variant_type in {"B", "C"}:
        result = _diversify_variant_items(result, version, db, variant_type)
        result = rebalance_domain_quotas(result)
        result = close_professional_lo_gaps(result)
    # Nothing after this point may add an unverified real discipline. Removed
    # credits are filled only by explicit bridge modules, so the UI never
    # presents a catalogue placeholder as an evidence-backed course.
    result = admit_real_courses(result)
    result = top_up_with_credit_bridges(result)
    result = close_professional_lo_gaps(result)
    result = admit_real_courses(result)
    result = top_up_with_credit_bridges(result)
    result = _trim_to_target_credits(result, target, db)
    for item in result:
        course = courses.get(item.get("course_id"))
        domain_index = project_domain_index(course) if course else None
        if domain_index in (0, 1) and project_domains[domain_index]:
            item["domain"] = project_domains[domain_index]
    return _unique_items_by_title(result)


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
    target_los = [lo.lo_code for lo in project_version.learning_outcomes] or []
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
    ]
    target_los = [lo.lo_code for lo in project_version.learning_outcomes] or []
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
            "credits": 5,
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
    learning_outcomes = list(project_version.learning_outcomes)
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


def schedule_courses(courses: List[Dict], num_semesters: int, nominal_load: int, db: Session) -> Dict[int, List[Dict]]:
    courses = _unique_items_by_title(courses)
    schedule = {semester: [] for semester in range(1, num_semesters + 1)}
    loads = {semester: 0 for semester in schedule}
    lower, upper = max(0, nominal_load - 3), nominal_load + 3
    course_map = {item.get("course_id"): item for item in courses if item.get("course_id") is not None}
    depth_cache = {}
    def depth(cid, path=None):
        if cid in depth_cache: return depth_cache[cid]
        path = path or set()
        if cid in path: return num_semesters
        item = course_map.get(cid)
        if not item: return 0
        parents = [pid for pid in item.get("prerequisites", []) if pid in course_map]
        value = 0 if not parents else 1 + max(depth(pid, path | {cid}) for pid in parents)
        depth_cache[cid] = value; return value
    required_ids = {prerequisite for item in courses for prerequisite in (item.get("prerequisites", []) or [])}
    dependents = {}
    for item in courses:
        for prerequisite in item.get("prerequisites", []) or []:
            if prerequisite in course_map:
                dependents.setdefault(prerequisite, []).append(item.get("course_id"))
    tail_cache = {}
    def tail_depth(cid, path=None):
        if cid in tail_cache: return tail_cache[cid]
        path = path or set()
        if cid in path: return 0
        children = [child for child in dependents.get(cid, []) if child in course_map]
        value = 0 if not children else 1 + max(tail_depth(child, path | {cid}) for child in children)
        tail_cache[cid] = value
        return value
    ordered = sorted(courses, key=lambda item: (depth(item.get("course_id")) if item.get("course_id") else 0, 0 if item.get("course_id") in required_ids else 1, -(item.get("credits") or 0)))
    placed = {}
    for item in ordered:
        prereq_semesters = [placed[p] for p in item.get("prerequisites", []) if p in placed]
        earliest = min(max(prereq_semesters, default=0) + 1, num_semesters)
        regulatory_semester = (
            int(item.get("recommended_semester") or 1)
            if item.get("regulatory_required") and str(item.get("type") or "").startswith("goso_")
            else _late_stage_min_semester(item.get("title"), num_semesters)
        )
        earliest = max(earliest, min(num_semesters, regulatory_semester))
        earliest = max(earliest, _complexity_min_semester(item, num_semesters))
        cid = item.get("course_id")
        bridge_id = item.get("bridge_module_id")
        if bridge_id is not None:
            bridge = db.query(BridgeModule).filter(BridgeModule.id == bridge_id).first()
            if bridge and (bridge.course_id or "").startswith(("CORE_BRIDGE_", "SECONDARY_")):
                recommended_bridge_semester = int(bridge.recommended_semester or item.get("recommended_semester") or 1)
                item["recommended_semester"] = recommended_bridge_semester
                item["latest_semester"] = min(num_semesters, recommended_bridge_semester + 1)
        latest = max(earliest, min(
            int(item.get("latest_semester") or num_semesters),
            _foundation_max_semester(item.get("title"), num_semesters),
            num_semesters - (tail_depth(cid) if cid is not None else 0),
        ))
        item["latest_semester"] = latest
        candidates = list(range(earliest, latest + 1))
        valid = [s for s in candidates if loads[s] + (item.get("credits") or 0) <= upper]
        pool = valid or candidates
        recommended = item.get("recommended_semester")
        target = min(
            pool,
            key=lambda semester: (
                abs(semester - int(recommended)) if recommended else 0,
                semester,
            ),
        )
        schedule[target].append(item); loads[target] += item.get("credits") or 0
        if item.get("course_id") is not None: placed[item["course_id"]] = target
    changed = True
    while changed:
        changed = False
        semester_by_course = {item["course_id"]: semester for semester, items in schedule.items() for item in items if item.get("course_id") is not None}
        for target_semester in [s for s in schedule if loads[s] < lower]:
            for donor_semester in sorted(schedule, key=lambda s: loads[s], reverse=True):
                if donor_semester == target_semester: continue
                for item in list(schedule[donor_semester]):
                    credits = item.get("credits") or 0
                    if item.get("regulatory_required") and target_semester != int(item.get("recommended_semester") or donor_semester):
                        continue
                    if target_semester < max(
                        _late_stage_min_semester(item.get("title"), num_semesters),
                        _complexity_min_semester(item, num_semesters),
                    ):
                        continue
                    if loads[donor_semester] - credits < lower or loads[target_semester] + credits > upper: continue
                    parent_semesters = [semester_by_course.get(p, 0) for p in item.get("prerequisites", []) or []]
                    child_semesters = [semester_by_course.get(d, num_semesters + 1) for d in dependents.get(item.get("course_id"), [])]
                    if parent_semesters and max(parent_semesters) >= target_semester: continue
                    if child_semesters and min(child_semesters) <= target_semester: continue
                    if not _move_item(schedule, donor_semester, target_semester, item):
                        continue
                    loads[donor_semester] -= credits; loads[target_semester] += credits
                    changed = True; break
                if changed: break
            if changed: break
    return schedule


def calculate_plan_metrics(schedule, selected_courses, project_version, db, verification=None) -> Dict:
    verification = verification or verify_curriculum_plan(schedule, project_version, db)
    international_quality = evaluate_international_quality(schedule, project_version, db, verification)
    selection_method = "nsga2" if any(item.get("selection_method") == "nsga2" for item in selected_courses) else "deterministic_bridge_heuristic"
    optimizer = {
        "name": "NSGA-II" if selection_method == "nsga2" else "Deterministic bridge heuristic",
        "selection_method": selection_method,
    }
    if selection_method == "nsga2":
        optimizer.update({
            "population": settings.NSGA2_POPULATION,
            "generations": settings.NSGA2_GENERATIONS,
            "crossover_probability": settings.NSGA2_CROSSOVER_PROBABILITY,
            "mutation_probability": settings.NSGA2_MUTATION_PROBABILITY,
            "objectives": ["LO coverage", "redundancy", "domain entropy"],
        })
    return {"total_credits": verification["total_credits"], "target_credits": verification["target_credits"], "total_courses": len(selected_courses), "num_bridge_modules": sum(1 for c in selected_courses if c.get("bridge_module_id")), "lo_coverage_percentage": round(verification["average_lo_coverage"] * 100, 1), "min_lo_coverage": verification["min_lo_coverage"], "evidence_count": verification["evidence_count"], "redundancy": verification["redundancy"], "prerequisite_violations": len(verification["prerequisite_violations"]), "semester_load_violations": len(verification["semester_load_violations"]), "feasible": verification["feasible"], "optimizer": optimizer, "international_quality": international_quality, "verification": verification}











