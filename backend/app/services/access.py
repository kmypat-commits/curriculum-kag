"""Object-level authorization for project-owned resources.

Authentication answers *who* is calling an endpoint.  This module answers
whether that user may see the particular project/version/plan.  Keeping the
check in one dependency prevents individual routers from accidentally
forgetting the ownership condition.
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.plan import Plan
from app.models.project import Project, ProjectVersion
from app.models.bridge_module import BridgeModule
from app.models.user import User
from app.services.auth import get_current_user
from app.services.rbac import check_permission, has_role


def is_admin(user: User) -> bool:
    return has_role(user, "admin")


def _deny() -> HTTPException:
    # Do not disclose whether another user's object exists.
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ресурс не найден")


def may_access_project(user: User, project: Project | None) -> bool:
    return bool(project and (is_admin(user) or project.created_by == user.id))


def require_project_access(db: Session, user: User, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not may_access_project(user, project):
        raise _deny()
    return project


async def require_project_object_access(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """FastAPI dependency wrapper for project-id object routes."""
    require_project_access(db, current_user, project_id)
    return current_user


def require_version_access(db: Session, user: User, project_version_id: int) -> ProjectVersion:
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not version or not may_access_project(user, version.project):
        raise _deny()
    return version


def require_plan_access(db: Session, user: User, plan_id: int) -> Plan:
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan or not may_access_project(user, plan.project_version.project):
        raise _deny()
    return plan


async def require_project_version_access(
    project_version_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """FastAPI dependency usable at router level.

    Global routes in a mixed router have no version parameter; those are
    intentionally left to their own global permission dependency.
    """
    if project_version_id is not None:
        require_version_access(db, current_user, project_version_id)
    return current_user


async def require_plan_object_access(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """FastAPI dependency for routes keyed by plan_id rather than version_id."""
    require_plan_access(db, current_user, plan_id)
    return current_user


async def require_syllabus_entity_access(
    kind: str,
    entity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Authorize syllabus generation by its actual entity type."""
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind == "course":
        if not check_permission(current_user, "repository", "read"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return current_user
    if normalized_kind == "bridge":
        bridge = db.query(BridgeModule).filter(BridgeModule.id == entity_id).first()
        if not bridge:
            raise _deny()
        require_version_access(db, current_user, bridge.project_version_id)
        return current_user
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Тип должен быть дисциплиной или bridge-модулем")
