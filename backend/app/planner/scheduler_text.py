"""Text-only helpers used by curriculum scheduling rules."""
import re


def short_lo_theme(lo) -> str:
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


def has_domain_term(text: str, terms: tuple[str, ...]) -> bool:
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
