from typing import List
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.user import User, Role, Permission


def check_permission(user: User, resource: str, action: str) -> bool:
    """Check if user has permission for a resource and action"""
    for role in user.roles:
        for permission in role.permissions:
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
    """Decorator to require a specific permission"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract user from kwargs
            current_user = kwargs.get('current_user')
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )
            
            if not check_permission(current_user, resource, action):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied: {action} on {resource}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


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
    """Get all permissions for a user"""
    permissions = []
    seen = set()
    
    for role in user.roles:
        for permission in role.permissions:
            key = f"{permission.resource}:{permission.action}"
            if key not in seen:
                permissions.append({
                    "resource": permission.resource,
                    "action": permission.action
                })
                seen.add(key)
    
    return permissions
