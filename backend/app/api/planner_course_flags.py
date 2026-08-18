"""Small persistence routes for regeneration exclusions and expert flags."""

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit import AuditEvent
from app.models.course import Course
from app.models.project import ProjectVersion
from app.models.user import User
from app.services.auth import get_current_user

router = APIRouter()


@router.post("/{project_version_id}/course-exclusions")
async def update_course_exclusion(
    project_version_id: int,
    course_id: int = Body(...),
    excluded: bool = Body(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist a course exclusion for subsequent A/B/C regeneration."""
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Версия проекта не найдена")
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Дисциплина не найдена")
    goso_applies = str((version.project.constraints_json or {}).get("jurisdiction") or "INTERNATIONAL").upper() == "KZ"
    if excluded and goso_applies and str(course.course_id or "").startswith("GOSO-KZ-"):
        raise HTTPException(status_code=400, detail="Обязательную дисциплину ГОСО РК нельзя удалить или заменить")
    constraints = dict(version.project.constraints_json or {})
    excluded_ids = {int(value) for value in (constraints.get("excluded_course_ids") or []) if str(value).isdigit()}
    (excluded_ids.add if excluded else excluded_ids.discard)(course.id)
    constraints["excluded_course_ids"] = sorted(excluded_ids)
    version.project.constraints_json = constraints
    db.add(AuditEvent(
        user_id=current_user.id,
        action="exclude_course_from_regeneration" if excluded else "restore_course_for_regeneration",
        entity_type="course",
        entity_id=course.id,
        details_json={"project_version_id": project_version_id, "course_title": course.title, "excluded": excluded},
    ))
    db.commit()
    return {
        "course_id": course.id,
        "course_title": course.title,
        "excluded": excluded,
        "excluded_course_ids": sorted(excluded_ids),
        "requires_regeneration": True,
        "message": "Дисциплина отмечена для исключения. При следующем построении A/B/C она не попадёт в планы." if excluded else "Исключение снято. Дисциплина снова может участвовать в следующем построении.",
    }


@router.post("/{project_version_id}/confirm-suspicious-course")
async def confirm_suspicious_course(
    project_version_id: int,
    course_id: int = Body(...),
    reason: str = Body("expert_confirmed"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Expert-confirm a course marked as suspicious by the automatic audit."""
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Версия проекта не найдена")
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Дисциплина не найдена")
    constraints = dict(version.project.constraints_json or {})
    confirmed = {int(value) for value in (constraints.get("confirmed_suspicious_course_ids") or []) if str(value).isdigit()}
    excluded = {int(value) for value in (constraints.get("excluded_course_ids") or []) if str(value).isdigit()}
    confirmed.add(course.id)
    excluded.discard(course.id)
    constraints["confirmed_suspicious_course_ids"] = sorted(confirmed)
    constraints["excluded_course_ids"] = sorted(excluded)
    version.project.constraints_json = constraints
    db.add(AuditEvent(
        user_id=current_user.id,
        action="confirm_suspicious_course",
        entity_type="course",
        entity_id=course.id,
        details_json={"project_version_id": project_version_id, "course_title": course.title, "reason": reason},
    ))
    db.commit()
    return {
        "status": "confirmed",
        "course_id": course.id,
        "course_title": course.title,
        "confirmed_suspicious_course_ids": sorted(confirmed),
        "excluded_course_ids": sorted(excluded),
        "requires_regeneration": False,
        "message": "Эксперт подтвердил дисциплину. Она останется в плане и больше не будет показываться как сомнительная.",
    }
