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
    physician_depth = ("клиническ", "диагност", "лечени", "хирург", "терапевт", "внутренние болезни", "акуш", "гинек", "педиатр", "офтальм", "онколог", "кардио", "уролог", "реаним", "стоматолог", "пропедевтик", "врачебн практик", "clinical diagnostics", "clinical diagnosis", "surgery", "treatment")
    if not _has_domain_term(text, physician_depth) or _has_domain_term(text, explicit_digital):
        return True
    return 0 < int(course.credits or 0) <= 7


def has_foreign_professional_title(course, project_domains: list[str]) -> bool:
    """Detect a professional context not represented by selected fields."""
    title = _title_key(course.title)
    domains = " ".join(project_domains).casefold()
    context_groups = (
        (("маркетинг", "marketing", "бизнес коммуникац", "business communication", "цифровая экономика", "digital economy", "экономик", "предприяти", "enterprise management", "комплексная логистика", "логистика", "logistics", "бухгалтер", "accounting", "финанс", "finance"), ("бизнес", "управлен", "эконом", "менедж", "маркет", "логист", "финанс", "account", "business", "management", "econom", "marketing", "logistics", "finance")),
        (("промышленная безопасность", "industrial safety"), ("промышлен", "производ", "инженер", "безопасность труда", "industrial", "manufactur", "engineering", "occupational safety")),
        (("эмоциональн", "эмоциональный интеллект", "emotional intelligence"), ("психолог", "человеческ ресурс", "hr", "управлен", "psycholog", "human resource", "management")),
    )
    return any(_has_domain_term(title, title_markers) and not _has_domain_term(domains, allowed) for title_markers, allowed in context_groups)
