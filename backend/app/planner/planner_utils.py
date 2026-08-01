"""Pure presentation and key-normalization helpers for the planner API."""
import re
import unicodedata
from typing import Any
from app.planner.goso import GOSO_DISPLAY_TITLES


def goso_definition_code(course: Any) -> str:
    code = str(getattr(course, "course_id", "") or "")
    return code.removeprefix("GOSO-KZ-") if code.startswith("GOSO-KZ-") else ""


def course_display_title(course: Any, fallback: str = "Неизвестная дисциплина") -> str:
    code = goso_definition_code(course)
    return GOSO_DISPLAY_TITLES.get(code) or getattr(course, "title", None) or fallback


def title_key(title: str | None) -> str:
    value = unicodedata.normalize("NFKC", str(title or "")).casefold()
    return " ".join(re.findall(r"\w+", value, flags=re.UNICODE))


def compact_lo_label(target_los: list[str]) -> str:
    values = [str(value).strip() for value in target_los if str(value).strip() and not str(value).startswith("LO-GOSO-")]
    if not values:
        return "междисциплинарных результатов"
    if len(values) <= 2:
        return ", ".join(values)
    return ", ".join(values[:2]) + f" и ещё {len(values) - 2}"
