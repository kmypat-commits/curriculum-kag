"""Seed the isolated SQLite account used by the real browser smoke job."""

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base, SessionLocal, engine
from app.models.user import Role, User
from app.services.auth import get_password_hash


Base.metadata.create_all(bind=engine)
with SessionLocal.begin() as db:
    role = db.query(Role).filter(Role.name == "admin").first()
    if role is None:
        role = Role(name="admin", description="CI browser smoke administrator")
        db.add(role)
        db.flush()
    user = db.query(User).filter(User.email == "browser-smoke@example.test").first()
    if user is None:
        user = User(
            email="browser-smoke@example.test",
            full_name="Browser Smoke Administrator",
            hashed_password=get_password_hash("browser-smoke-password"),
            is_active=1,
            roles=[role],
        )
        db.add(user)

print("browser smoke seed ready")
