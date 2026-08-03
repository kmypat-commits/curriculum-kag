"""Pure domain-label and course-domain checks used by the scheduler."""
from __future__ import annotations

from app.planner.scheduler_utils import title_key as _title_key


def course_domain_matches(course, project_domains: list[str]) -> bool:
    domain = (course.domain or "").lower().strip()
    return bool(domain) and any(d and (d in domain or domain in d) for d in project_domains)


def invalid_project_domain_label(value: str | None) -> bool:
    normalized = _title_key(value)
    if not normalized or "?" in normalized:
        return True
    return sum(1 for char in normalized if char.isalpha()) < 3
