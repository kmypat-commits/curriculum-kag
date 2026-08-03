"""Shared language normalization for API and repository boundaries."""

SUPPORTED_LANGUAGES = ("ru", "kk", "en")
_ALIASES = {
    "ru": "ru", "rus": "ru", "russian": "ru",
    "kk": "kk", "kz": "kk", "kaz": "kk", "kazakh": "kk",
    "en": "en", "eng": "en", "english": "en",
}


def normalize_language(value: str | None, default: str = "ru") -> str:
    """Return one of the supported interface language codes."""
    fallback = _ALIASES.get(str(default or "ru").strip().lower(), "ru")
    return _ALIASES.get(str(value or "").strip().lower(), fallback)


def epvo_payload_suffix(value: str | None) -> str:
    """Return the EPVO payload field suffix for a normalized language."""
    return {"ru": "Ru", "kk": "Kz", "en": "En"}[normalize_language(value)]
