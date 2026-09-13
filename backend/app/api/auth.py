from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
import secrets
from app.database import get_db
from app.config import settings
from app.models.user import User
from app.models.audit import AuditEvent
from app.services.auth import (
    verify_password,
    create_access_token,
    get_current_user
)
from app.services.rbac import get_user_permissions

router = APIRouter()


class Token(BaseModel):
    access_token: str
    token_type: str


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    roles: list
    permissions: list


CSRF_COOKIE = "csrf_token"


def _authenticate(form_data: OAuth2PasswordRequestForm, db: Session) -> User:
    """Authenticate without exposing account existence or password details."""
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный адрес электронной почты или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Учётная запись отключена")
    return user


def _record_cli_auth_event(db: Session, user: User, action: str) -> None:
    """Record token lifecycle events without logging token material."""
    add = getattr(db, "add", None)
    commit = getattr(db, "commit", None)
    if not callable(add) or not callable(commit):
        return
    try:
        add(AuditEvent(user_id=user.id, action=action, entity_type="user", entity_id=user.id, details_json={"token_use": "cli"}))
        commit()
    except Exception:
        db.rollback()


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    response: Response = None,
):
    """Browser login: issue only HttpOnly/session cookies, never a JSON JWT."""
    user = _authenticate(form_data, db)
    _record_cli_auth_event(db, user, "cli_token_issued")
    access_token = create_access_token(data={"sub": user.email, "token_use": "browser"})
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    # Double-submit token: readable by the SPA, while the auth JWT remains
    # HttpOnly.  State-changing cookie requests are checked at the API edge.
    response.set_cookie(
        key=CSRF_COOKIE,
        value=secrets.token_urlsafe(32),
        httponly=False,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    
    # Return ``None`` so FastAPI preserves cookies set on the injected response.
    return None


@router.post("/token", response_model=Token)
async def issue_cli_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Explicit non-browser token exchange for CLI and automation clients."""
    user = _authenticate(form_data, db)
    return {
        "access_token": create_access_token(
            data={"sub": user.email, "token_use": "cli", "token_version": getattr(user, "cli_token_version", 0) or 0},
            expires_delta=timedelta(minutes=settings.CLI_TOKEN_EXPIRE_MINUTES),
        ),
        "token_type": "bearer",
    }


@router.post("/token/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_cli_tokens(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke all CLI bearer tokens for the current account."""
    current_user.cli_token_version = int(getattr(current_user, "cli_token_version", 0) or 0) + 1
    db.commit()
    _record_cli_auth_event(db, current_user, "cli_tokens_revoked")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    response.delete_cookie(
        key="access_token",
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(key=CSRF_COOKIE, secure=settings.AUTH_COOKIE_SECURE, samesite="lax", path="/")


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user information"""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "roles": [role.name for role in current_user.roles],
        "permissions": get_user_permissions(current_user)
    }
