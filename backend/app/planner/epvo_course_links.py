"""Canonical EPVO-to-course link resolution.

Imports may contain both an ``approved_course_id`` link and an ``EPVO-*``
course code.  Keeping resolution here prevents each planner stage from
implementing a subtly different duplicate-row policy.
"""

from collections.abc import Mapping


def epvo_code_index(courses: Mapping[int, object]) -> dict[int, int]:
    """Return normalized EPVO row id -> local course id for the given courses."""
    result: dict[int, int] = {}
    for course in courses.values():
        code = str(getattr(course, "course_id", "") or "")
        if not code.startswith("EPVO-"):
            continue
        raw_id = code.split("-", 1)[1]
        if raw_id.isdigit():
            result[int(raw_id)] = int(course.id)
    return result


def linked_course_id(row: object, epvo_index: Mapping[int, int]) -> int | None:
    """Prefer the canonical EPVO code link, then fall back to approval link."""
    row_id = getattr(row, "id", None)
    return (epvo_index.get(int(row_id)) if row_id is not None else None) or getattr(
        row, "approved_course_id", None
    )
