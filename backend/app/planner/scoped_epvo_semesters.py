from __future__ import annotations

from statistics import median
from typing import Dict, List

from sqlalchemy import or_

from app.models.course import Course
from app.models.epvo import EpvoDisciplineNormalized
from app.services.epvo_repository import epvo_row_matches_education_level


def apply_scoped_epvo_semesters(items: List[Dict], project_version, db) -> List[Dict]:
    """Attach typical semester evidence for the selected EPVO scope."""
    constraints = project_version.project.constraints_json or {}
    groups = {
        str(value).strip()
        for value in (constraints.get("group_code"), constraints.get("secondary_group_code"))
        if str(value or "").strip()
    }
    directions = {
        str(value).strip()
        for value in (constraints.get("direction_code"), constraints.get("secondary_direction_code"))
        if str(value or "").strip()
    }
    max_semesters = int(constraints.get("total_semesters") or 0)

    local_ids = {
        int(item["course_id"])
        for item in items
        if item.get("course_id") is not None
        and not item.get("regulatory_required")
        and item.get("bridge_module_id") is None
    }
    local_to_epvo: Dict[int, int] = {}
    for course in db.query(Course).filter(Course.id.in_(local_ids or {-1})).all():
        code = str(course.course_id or "")
        if code.startswith("EPVO-"):
            try:
                local_to_epvo[int(course.id)] = int(code.split("-", 1)[1])
            except (TypeError, ValueError):
                continue

    epvo_ids = set(local_to_epvo.values())
    scoped: Dict[int, List[int]] = {}
    if epvo_ids and (groups or directions):
        rows = db.query(EpvoDisciplineNormalized).filter(
            or_(
                EpvoDisciplineNormalized.id.in_(epvo_ids),
                EpvoDisciplineNormalized.approved_course_id.in_(epvo_ids),
            )
        ).all()
        for row in rows:
            if not epvo_row_matches_education_level(row, constraints.get("education_level")):
                continue
            if not (
                groups.intersection(row.group_codes or [])
                or directions.intersection(row.direction_codes or [])
            ):
                continue
            value = int(row.typical_semester or 0)
            if 1 <= value and (not max_semesters or value <= max_semesters):
                approved_id = int(row.approved_course_id) if row.approved_course_id else None
                key = int(row.id) if int(row.id) in epvo_ids else approved_id
                if key is None:
                    continue
                scoped.setdefault(key, []).append(value)

    for item in items:
        local_id = int(item["course_id"]) if item.get("course_id") is not None else None
        epvo_id = local_to_epvo.get(local_id, local_id) if local_id is not None else None
        if epvo_id in scoped:
            item["recommended_semester"] = int(round(median(scoped[epvo_id])))
            item["_scoped_epvo_semester"] = True
    return items
