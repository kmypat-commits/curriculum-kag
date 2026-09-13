"""Pure domain-label and course-domain checks used by the scheduler."""
from __future__ import annotations

from app.planner.scheduler_utils import title_key as _title_key
from app.planner.scheduler_text import has_domain_term as _has_domain_term
from app.planner.domain_evidence import domain_label_matches as _domain_label_matches
from app.models.course import Course


def course_domain_matches(course, project_domains: list[str]) -> bool:
    # GOSO-required research-methods courses are domain-neutral.  Some EPVO
    # imports inherit the source programme's domain (including ``forensics``)
    # even though the course is a general academic requirement; rejecting it
    # creates a false cross-domain failure for otherwise valid programmes.
    title = _title_key(getattr(course, "title", ""))
    if any(marker in title for marker in (
        "методы научных исследований",
        "методология научного исследования",
        "methods of scientific research",
        "research methodology",
    )):
        return True
    # Use the same canonical RU/KK/EN alias matcher as verification and quota
    # repair. Raw substring checks made legacy labels such as Medicine and
    # Здравоохранение disagree across planner stages.
    return _domain_label_matches(getattr(course, "domain", ""), project_domains)


def invalid_project_domain_label(value: str | None) -> bool:
    normalized = _title_key(value)
    if not normalized or "?" in normalized:
        return True
    return sum(1 for char in normalized if char.isalpha()) < 3


def is_interdisciplinary_title_relevant(course, project_domains: list[str]) -> bool:
    """Require a course to fit the professional role of its project domains."""
    domains = " ".join(project_domains).lower()
    has_it = any(term in domains for term in ("it", "информ", "computer", "кибер"))
    has_forensics = any(term in domains for term in ("forensic", "криминал", "расслед", "след"))
    is_medicine_it = any(term in domains for term in ("medicine", "мед", "здрав")) and has_it
    if not is_medicine_it and not (has_it and has_forensics):
        return True
    full_text = _title_key(" ".join([course.title or "", course.description or ""]))
    if not full_text:
        return False
    medical_terms = ("мед", "здрав", "клиник", "пациент", "врач", "био", "анатом", "физиолог", "фармак", "эпидеми", "вирус", "бактер", "гистолог", "иммун", "хирург", "инфекц", "патолог", "онколог", "уролог", "невролог", "педиатр")
    it_terms = ("it", "информ", "цифр", "данн", "data", "программ", "алгоритм", "автомат", "ai", "искусствен", "модел", "mathlab", "3d", "телемед", "сеть", "сетей", "баз", "cloud", "облач", "machine learning", "кибер", "безопас", "сервер", "вычисл", "software", "computer")
    forensic_terms = ("forensic", "криминалист", "расслед", "доказател", "экспертн", "судеб", "процессу", "инцидент", "угроз", "вредонос", "malware", "киберпреступ", "цифров", "журнал", "лог", "osint", "атак", "уязвим", "сохранен", "документирован", "цепочк")
    domain = (course.domain or "").lower()
    if has_it and has_forensics:
        if not _has_domain_term(full_text, it_terms + forensic_terms):
            return False
        if any(term in domain for term in ("forensic", "криминал", "расслед", "след")):
            return _has_domain_term(full_text, forensic_terms)
        return _has_domain_term(full_text, it_terms + forensic_terms)
    if any(term in domain for term in ("medicine", "мед", "здрав")):
        return _has_domain_term(full_text, medical_terms)
    if any(term in domain for term in ("it", "информ", "computer")):
        return _has_domain_term(full_text, it_terms)
    return True


def is_it_medicine_support_course(course, project_domains: list[str]) -> bool:
    """Reject physician-training depth from an IT + medicine programme."""
    domains = " ".join(project_domains).casefold()
    is_it_medicine = any(marker in domains for marker in ("it", "информ", "computer", "software", "цифр")) and any(marker in domains for marker in ("мед", "здрав", "medicine", "medical", "health"))
    if not is_it_medicine:
        return True
    text = _title_key(" ".join([course.title or "", course.description or ""]))
    explicit_digital = ("информационн систем", "медицинская информатика", "медицинской информатики", "медицинскую информатику", "цифр", "алгоритм", "программ", "телемед", "биоинформ", "искусствен", "machine learning", "data science", "database", "digital", "information system", "software", "computer", "электронн медицинск", "электронн здравоохран")
    physician_depth = ("клиническ", "диагност", "лечени", "хирург", "терапевт", "внутренние болезни", "акуш", "гинек", "педиатр", "офтальм", "онколог", "кардио", "уролог", "нейропат", "патолог", "реаним", "стоматолог", "пропедевтик", "врачебн практик", "clinical diagnostics", "clinical diagnosis", "surgery", "treatment")
    if not _has_domain_term(text, physician_depth) or _has_domain_term(text, explicit_digital):
        return True
    # A short generic foundation may provide medical context for IT students,
    # but a specialty clinical block (neuropathology, surgery, etc.) cannot be
    # admitted merely because it is small.
    compact_foundation = str(course.title or "").casefold().strip().startswith("основы ") and int(course.credits or 0) <= 5
    return compact_foundation and not any(
        marker in text for marker in ("нейропат", "патолог", "хирург", "кардио", "онколог", "уролог", "офтальм")
    )


def has_foreign_professional_title(course, project_domains: list[str]) -> bool:
    """Detect a professional context not represented by selected fields."""
    title = _title_key(course.title)
    # A replacement-character title is a data-quality issue, not reliable
    # semantic evidence.  Treating mojibake as a real word can accidentally
    # match markers such as ``предприяти`` and reject a valid EPVO course;
    # encoding audits handle these rows separately and the planner can then
    # request a reviewed translation.
    if "\ufffd" in title:
        return False
    domains = " ".join(project_domains).casefold()
    course_domain = str(getattr(course, "domain", "") or "").casefold()
    # EPVO often stores enterprise/1C courses under the IT domain.  For an
    # explicitly IT-scoped programme that is a valid application context only
    # when the title still exposes an IT/data/project context.  A bare
    # business course such as ``Маркетинговый менеджмент`` must not pass just
    # because a deduplicated catalogue row inherited ``domain=it``.
    if any(marker in course_domain for marker in ("it", "информ", "computer")) and any(
        marker in domains for marker in ("it", "информ", "computer", "6b", "7m", "8d")
    ):
        it_context = (
            "it", "информ", "цифр", "данн", "технолог", "систем",
            "программ", "алгоритм", "проект", "software", "computer",
            "data", "digital", "database", "business intelligence",
            "1с", "enterprise resource",
        )
        if _has_domain_term(title, it_context):
            return False
    # Cross-domain foundation subjects (for example, Health Economics) are
    # valid when the title explicitly names the selected secondary field.
    if any(
        marker in title
        for marker in ("здрав", "медицин", "medicine", "medical", "health", "клинич")
    ) and any(
        marker in domains
        for marker in ("здрав", "медицин", "medicine", "medical", "health")
    ):
        return False
    context_groups = (
        (("маркетинг", "marketing", "бизнес коммуникац", "business communication", "цифровая экономика", "digital economy", "экономик", "предприяти", "enterprise management", "комплексная логистика", "логистика", "logistics", "бухгалтер", "accounting", "финанс", "finance"), ("бизнес", "управлен", "эконом", "менедж", "маркет", "логист", "финанс", "account", "business", "management", "econom", "marketing", "logistics", "finance")),
        (("промышленная безопасность", "industrial safety"), ("промышлен", "производ", "инженер", "безопасность труда", "industrial", "manufactur", "engineering", "occupational safety")),
        (("эмоциональн", "эмоциональный интеллект", "emotional intelligence"), ("психолог", "человеческ ресурс", "hr", "управлен", "psycholog", "human resource", "management")),
        # A course can belong to the broad legal catalogue yet still teach a
        # separate regulated sector.  Keep that sector out unless it is
        # explicitly named in the programme fields; otherwise generic group
        # membership lets customs or labour-law subjects fill a cyber/legal
        # curriculum credit slot.
        (("тамож", "customs", "внешнеэкономическ", "foreign trade"), ("тамож", "customs", "внешнеэкономическ", "foreign trade")),
        (("трудов", "социального обеспеч", "labor law", "social security"), ("трудов", "социального обеспеч", "labor", "social security")),
    )
    return any(_has_domain_term(title, title_markers) and not _has_domain_term(domains, allowed) for title_markers, allowed in context_groups)
from collections.abc import Callable, Mapping, Sequence
from typing import Any


def find_invalid_project_domain_courses(
    schedule: Mapping[int, Sequence[Mapping[str, Any]]],
    db: Any,
    project_domains: Sequence[str],
    declared_secondary_domain: str,
    is_project_domain: Callable[[Any], bool],
    is_general_course: Callable[[Any], bool] | None = None,
) -> list[dict[str, Any]]:
    """Return non-regulatory courses that violate the declared programme domain.

    This is deliberately a pure audit boundary: it never removes or rewrites
    schedule items.  Keeping it separate from the planner pipeline prevents a
    late repair from silently weakening the final admission check.
    """
    invalid: list[dict[str, Any]] = []
    prerequisite_ids = {
        int(prerequisite_id)
        for items in schedule.values()
        for item in items
        for prerequisite_id in (item.get("prerequisites") or [])
        if str(prerequisite_id).isdigit()
    }
    # Scheduling may materialize prerequisite rows without copying the
    # relationship into every transient item snapshot. Resolve the graph
    # from the persisted Course relation as the authoritative source.
    scheduled_course_ids = {
        int(item["course_id"])
        for items in schedule.values()
        for item in items
        if item.get("course_id") is not None
    }
    for course_id in scheduled_course_ids:
        course = db.get(Course, course_id)
        prerequisite_ids.update(
            int(prerequisite.id)
            for prerequisite in (getattr(course, "prerequisites", None) or [])
        )
    project_text = f"{declared_secondary_domain} {' '.join(project_domains)}"
    has_agriculture = any(
        token in project_text
        for token in ("agri", "agro", "farm", "сельск", "аграр", "агроном", "ауыл")
    )
    has_medical = any(
        token in project_text
        for token in ("medicine", "medical", "health", "медицин", "здрав", "clinical")
    )
    has_it = any(
        token in project_text
        for token in ("it", "информ", "computer", "цифр", "software")
    )
    has_law = any(
        token in project_text
        for token in ("law", "legal", "право", "юрид", "юриспруд", "криминал", "судеб")
    )
    for items in schedule.values():
        for item in items:
            if item.get("regulatory_required") or item.get("course_id") is None:
                continue
            course = db.get(Course, int(item["course_id"]))
            if course is None:
                continue
            # A prerequisite is an ordering dependency, not a professional
            # domain contribution. Its validity is checked by the prerequisite
            # graph verifier; applying the programme-domain quota to it caused
            # legitimate cross-domain foundation courses to be rejected.
            if course.id in prerequisite_ids:
                continue
            # General education courses are governed by the programme's
            # general-course budget, not by the professional-domain quota.
            # Treating them as domain violations made valid interdisciplinary
            # plans fail at the final boundary.
            if is_general_course is not None and is_general_course(course):
                continue
            item_domain = str(item.get("domain") or "").casefold().strip()
            canonical_domain = str(course.domain or "").casefold()
            medical = any(
                token in f"{item_domain} {canonical_domain}"
                for token in ("medicine", "medical", "health", "медицин", "здрав", "clinical")
            )
            # Legacy EPVO deduplication can retain a source-domain label from
            # Medicine on a valid cross-domain foundation course.  The
            # admission policy handles this case explicitly; the final domain
            # audit must not turn that source label into a false violation.
            if medical and not has_medical:
                continue
            item_has_domain = bool(item_domain) and (
                any(domain and (domain in item_domain or item_domain in domain) for domain in project_domains)
                or _domain_label_matches(item_domain, project_domains)
            )
            if is_project_domain(course) or item_has_domain:
                continue
            # A deduplicated EPVO record may retain a forensic source label
            # although its title is a valid IT foundation in an IT+agriculture
            # programme.  Preserve that evidence-backed exception explicitly.
            forensic = any(token in canonical_domain for token in ("forensic", "криминал", "расслед", "след"))
            title_is_it = any(
                token in str(course.title or "").casefold()
                for token in ("алгоритм", "данн", "программ", "информацион", "систем", "компьютер", "цифров", "кибер", "криминал", "computer", "data")
            )
            # EPVO deduplication may preserve a forensic source label for an
            # IT course in any interdisciplinary IT programme (not only the
            # historical IT+agriculture profile).  The title-level guard is
            # intentionally retained so unrelated forensic courses remain
            # rejected.
            if has_it and forensic and title_is_it:
                continue
            # In a Law + IT programme, digital/specialist forensics is not a
            # third, foreign domain: it is the professional intersection of
            # the two declared fields. EPVO's legacy ``forensics`` label is
            # therefore admissible only for this explicit pairing, while the
            # normal foreign-domain guard remains active for every other
            # programme profile.
            title_is_forensic = any(
                token in str(course.title or "").casefold()
                for token in ("forensic", "криминал", "расслед", "судеб", "digital evidence")
            )
            if has_it and has_law and forensic and title_is_forensic:
                continue
            invalid.append({"course_id": course.id, "title": course.title, "domain": course.domain})
    return invalid
