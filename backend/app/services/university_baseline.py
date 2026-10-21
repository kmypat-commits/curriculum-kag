"""Transactional confirmation and immutable loading of baseline revisions."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select

from app.models.course import Course
from app.models.project import ProjectVersion
from app.models.university_baseline import UniversityBaselineImport, UniversityBaselineRevision
from app.services.university_baseline_import import canonical_hash


def course_content_hash(course: Course) -> str:
    content = {
        "course_id": course.course_id,
        "title": course.title,
        "domain": course.domain,
        "credits": course.credits,
        "description": course.description,
        "topics": course.topics,
        "learning_outcomes": course.learning_outcomes,
        "assessment_methods": course.assessment_methods,
        "language": course.language,
        "cycle_component": course.cycle_component,
    }
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _resolved_rows(db, baseline_import: UniversityBaselineImport) -> list[dict]:
    rows = list(baseline_import.rows_json or [])
    mapping = {int(key): value for key, value in (baseline_import.mapping_json or {}).items()}
    if not rows or {int(row["source_row"]) for row in rows} != set(mapping):
        raise ValueError("mapping_incomplete")
    resolved = []
    for row in rows:
        course_id = mapping[int(row["source_row"])]
        course = db.get(Course, course_id)
        if course is None:
            raise ValueError("mapping_stale")
        current_hash = course_content_hash(course)
        if row.get("content_sha256") and row["content_sha256"] != current_hash:
            raise ValueError("mapping_stale")
        resolved.append({**row, "course_id": course.id, "content_sha256": current_hash})
    return resolved


def confirm_import(db, import_id: int, user_id: int) -> UniversityBaselineRevision:
    baseline_import = db.execute(select(UniversityBaselineImport).where(UniversityBaselineImport.id == import_id).with_for_update()).scalar_one()
    if baseline_import.status == "confirmed":
        return db.execute(select(UniversityBaselineRevision).where(UniversityBaselineRevision.import_id == import_id)).scalar_one()
    if baseline_import.status not in {"draft", "ready"}:
        raise ValueError("import_not_confirmable")
    version_lock = db.execute(select(ProjectVersion).where(ProjectVersion.id == baseline_import.project_version_id).with_for_update()).scalar_one()
    resolved = _resolved_rows(db, baseline_import)
    revision_number = db.execute(select(UniversityBaselineRevision.revision_number).where(UniversityBaselineRevision.project_version_id == version_lock.id).order_by(UniversityBaselineRevision.revision_number.desc())).scalars().first()
    revision_number = (revision_number or 0) + 1
    revision = UniversityBaselineRevision(
        project_version_id=version_lock.id,
        import_id=baseline_import.id,
        revision_number=revision_number,
        confirmed_by=user_id,
        source_sha256=baseline_import.source_sha256,
        canonical_sha256=canonical_hash(resolved),
        resolved_rows_json=resolved,
    )
    db.add(revision)
    baseline_import.status = "confirmed"
    db.flush()
    return revision


def load_revision(db, project_version_id: int, revision_id: int) -> UniversityBaselineRevision:
    revision = db.execute(select(UniversityBaselineRevision).where(UniversityBaselineRevision.id == revision_id, UniversityBaselineRevision.project_version_id == project_version_id)).scalar_one_or_none()
    if revision is None:
        raise ValueError("baseline_revision_not_found")
    return revision
