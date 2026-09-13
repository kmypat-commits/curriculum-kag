from __future__ import annotations

import math
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models.course import Course
from app.planner.course_policy import (
    course_curriculum_role as _course_curriculum_role,
    course_role_rank as _course_role_rank,
)
from app.planner.scheduler_utils import title_key as _title_key


def limit_general_course_items(
    items: List[Dict],
    courses: Dict[int, Course],
    project_domains: List[str],
    target_credits: int,
    max_percent: int = 20,
) -> List[Dict]:
    """Keep generic/domain-adjacent courses as support, not programme core."""
    if not items:
        return items
    max_general_credits = max(0, math.floor(target_credits * max_percent / 100))
    normalized = [dict(item) for item in items]
    selected_ids = {
        item.get("course_id") for item in normalized if item.get("course_id") is not None
    }
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
        if (
            course
            and not item.get("epvo_exact_scope")
            and _course_curriculum_role(course, project_domains) == "general"
        ):
            credits = int(item.get("credits") or course.credits or 0)
            general_credits += credits
            if course_id not in protected_ids:
                general_indexes.append(
                    (index, credits, _course_role_rank(course, project_domains), int(course_id or 0))
                )
    if general_credits <= max_general_credits:
        return normalized
    remove_indexes = set()
    for index, credits, _rank, _course_id in sorted(
        general_indexes, key=lambda row: (row[2], row[3])
    ):
        if general_credits <= max_general_credits:
            break
        remove_indexes.add(index)
        general_credits -= credits
    return [item for index, item in enumerate(normalized) if index not in remove_indexes]


def remap_equivalent_prerequisites(items: List[Dict], db: Session) -> List[Dict]:
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
            replacement = retained_by_title.get(
                prerequisite_titles.get(prerequisite_id, ""), prerequisite_id
            )
            if (
                replacement in selected_ids
                and replacement != item.get("course_id")
                and replacement not in remapped
            ):
                remapped.append(replacement)
        item["prerequisites"] = remapped
    return normalized
