from typing import List
from fastapi import Depends, HTTPException, status
from app.models.user import User, Role, Permission
from app.services.auth import get_current_user


# Authoritative fallback policy.  Database permissions can add narrower
# permissions, while this matrix keeps a fresh install secure and predictable.
ROLE_POLICY = {
    "admin": {("*", "*")},
    "methodist": {
        ("repository", "read"), ("repository", "write"),
        ("planner", "read"), ("planner", "write"), ("export", "read"),
        ("kag", "read"), ("kag", "feedback"), ("epvo", "read"),
    },
    "analyst": {
        ("repository", "read"), ("planner", "read"),
        ("export", "read"), ("kag", "read"), ("epvo", "read"),
    },
    "guest": {( "planner", "read"), ("export", "read")},
}


def check_permission(user: User, resource: str, action: str) -> bool:
    """Check if user has permission for a resource and action"""
    if any((resource, action) in ROLE_POLICY.get(role.name, set()) or
           ("*", "*") in ROLE_POLICY.get(role.name, set()) or
           (resource, "*") in ROLE_POLICY.get(role.name, set()) or
           ("*", action) in ROLE_POLICY.get(role.name, set()) for role in user.roles):
        return True
    for role in user.roles:
        # Role relationships can be partially populated in a stale session
        # or lightweight auth fixture. Missing permissions must mean "no extra
        # permission", never an internal 500.
        for permission in getattr(role, "permissions", None) or []:
            if permission.resource == resource and permission.action == action:
                return True
            # Check for wildcard permissions
            if permission.resource == "*" and permission.action == action:
                return True
            if permission.resource == resource and permission.action == "*":
                return True
            if permission.resource == "*" and permission.action == "*":
                return True
    return False


def require_permission(resource: str, action: str):
    """FastAPI dependency factory (safe signature; no decorator wrapping)."""
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if not check_permission(current_user, resource, action):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return current_user
    # Preserve a stable name for route inventory and OpenAPI/access audits.
    dependency.__name__ = f"require_permission_{resource}_{action}"
    return dependency


def has_role(user: User, role_name: str) -> bool:
    """Check if user has a specific role"""
    return any(role.name == role_name for role in user.roles)


def require_role(role_name: str):
    """Decorator to require a specific role"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            current_user = kwargs.get('current_user')
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )
            
            if not has_role(current_user, role_name):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role required: {role_name}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def get_user_permissions(user: User) -> List[dict]:
    """Return effective permissions, including the authoritative role policy."""
    permissions = []
    seen = set()

    for role in user.roles:
        for resource, action in ROLE_POLICY.get(role.name, set()):
            # Wildcard policy entries are enforced by check_permission but are
            # not useful as opaque UI rows; concrete permissions are expanded
            # below from the known application resource/action matrix.
            if resource == "*" or action == "*":
                continue
            key = f"{resource}:{action}"
            if key not in seen:
                permissions.append({"resource": resource, "action": action})
                seen.add(key)
        for permission in getattr(role, "permissions", None) or []:
            key = f"{permission.resource}:{permission.action}"
            if key not in seen:
                permissions.append({
                    "resource": permission.resource,
                    "action": permission.action
                })
                seen.add(key)
    
    return permissions
