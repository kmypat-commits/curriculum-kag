"""Pure domain-label and course-domain checks used by the scheduler."""
from __future__ import annotations

from app.planner.scheduler_utils import title_key as _title_key
from app.planner.scheduler_text import has_domain_term as _has_domain_term


def course_domain_matches(course, project_domains: list[str]) -> bool:
    domain = (course.domain or "").lower().strip()
    return bool(domain) and any(d and (d in domain or domain in d) for d in project_domains)


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
    # explicitly IT-scoped programme that is a valid application context, not
    # a foreign business programme; LO/EPVO evidence still controls admission.
    if any(marker in course_domain for marker in ("it", "информ", "computer")) and any(
        marker in domains for marker in ("it", "информ", "computer", "6b", "7m", "8d")
    ):
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
    )
    return any(_has_domain_term(title, title_markers) and not _has_domain_term(domains, allowed) for title_markers, allowed in context_groups)
