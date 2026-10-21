"""Owner-scoped university baseline import and confirmation routes."""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.course import Course
from app.models.university_baseline import UniversityBaselineImport, UniversityBaselineRevision
from app.models.user import User
from app.schemas.university_baseline import BaselineColumnMapping, BaselineMappingRequest
from app.services.access import require_version_access
from app.services.auth import get_current_user
from app.services.university_baseline import confirm_import, load_revision
from app.services.university_baseline_import import ImportValidationError, parse_source, validate_mapping


router = APIRouter(prefix="/{project_version_id}/baseline", tags=["planner-baseline"])


def _owned_import(db: Session, current_user: User, project_version_id: int, import_id: int) -> UniversityBaselineImport:
    require_version_access(db, current_user, project_version_id)
    item = db.execute(select(UniversityBaselineImport).where(UniversityBaselineImport.id == import_id, UniversityBaselineImport.project_version_id == project_version_id)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="baseline import not found")
    return item


@router.post("/import")
async def import_baseline(
    project_version_id: int,
    file: UploadFile = File(...),
    code: str = "code",
    title: str = "title",
    credits: str = "credits",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_version_access(db, current_user, project_version_id)
    data = await file.read()
    columns = BaselineColumnMapping(code=code, title=title, credits=credits).model_dump()
    try:
        rows = parse_source(data, file.filename or "", columns)
    except ImportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    source_sha256 = hashlib.sha256(data).hexdigest()
    item = UniversityBaselineImport(
        project_version_id=project_version_id,
        created_by=current_user.id,
        source_name=file.filename or "baseline",
        source_sha256=source_sha256,
        source_bytes=len(data),
        rows_json=rows,
        mapping_json={},
        status="draft",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "status": item.status, "source_sha256": item.source_sha256, "row_count": len(rows)}


@router.patch("/imports/{import_id}/mapping")
def map_baseline(
    project_version_id: int,
    import_id: int,
    payload: BaselineMappingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = _owned_import(db, current_user, project_version_id, import_id)
    mapping = {str(row.source_row): row.course_id for row in payload.rows}
    parsed_rows = list(item.rows_json or [])
    try:
        catalogue = {
            course.id: {
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
            for course in db.execute(select(Course)).scalars()
        }
        resolved = validate_mapping(parsed_rows, {int(k): v for k, v in mapping.items()}, catalogue)
    except (ImportValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    item.rows_json = resolved
    item.mapping_json = mapping
    item.status = "ready"
    db.commit()
    return {"id": item.id, "status": item.status, "mapped_rows": len(resolved)}


@router.post("/imports/{import_id}/confirm")
def confirm_baseline(
    project_version_id: int,
    import_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = _owned_import(db, current_user, project_version_id, import_id)
    try:
        revision = confirm_import(db, item.id, current_user.id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": revision.id, "revision_number": revision.revision_number, "canonical_sha256": revision.canonical_sha256, "status": "confirmed"}


@router.get("/revisions")
def list_baseline_revisions(project_version_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    require_version_access(db, current_user, project_version_id)
    revisions = db.execute(select(UniversityBaselineRevision).where(UniversityBaselineRevision.project_version_id == project_version_id).order_by(UniversityBaselineRevision.revision_number)).scalars().all()
    return [{"id": item.id, "revision_number": item.revision_number, "canonical_sha256": item.canonical_sha256, "confirmed_at": item.confirmed_at} for item in revisions]


@router.get("/revisions/{revision_id}")
def get_baseline_revision(project_version_id: int, revision_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    require_version_access(db, current_user, project_version_id)
    try:
        revision = load_revision(db, project_version_id, revision_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": revision.id, "revision_number": revision.revision_number, "canonical_sha256": revision.canonical_sha256, "resolved_rows": revision.resolved_rows_json, "confirmed_at": revision.confirmed_at}
