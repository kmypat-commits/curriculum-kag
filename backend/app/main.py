from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from sqlalchemy import text

# Fix for Passlib + Bcrypt 4.1.0+ compatibility on Python 3.14
try:
    import bcrypt
    # Monkeypatch bcrypt to avoid passlib internal errors
    if not hasattr(bcrypt, "__about__"):
        bcrypt.__about__ = type('about', (object,), {'__version__': bcrypt.__version__})
    
    # Also patch the password length limit check in some environments
    import passlib.handlers.bcrypt
    original_detect = passlib.handlers.bcrypt._bcrypt_detect_wrap_bug
    passlib.handlers.bcrypt._bcrypt_detect_wrap_bug = lambda: False
except (ImportError, AttributeError):
    pass

from app.config import settings
from app.api import auth, projects, repository, kag, planner, export_api, epvo as epvo_api, git_versions
from app.database import engine, Base
# Import all models to register them with Base
from app.models import user, project, course, plan, embedding, audit, bridge_module, syllabus, epvo

# Ensure all tables are created (required for SQLite if migrations aren't run)
Base.metadata.create_all(bind=engine)
with engine.begin() as connection:
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_epvo_disciplines_normalized_approved_course_id "
        "ON epvo_disciplines_normalized (approved_course_id)"
    ))

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Информационная система для автоматизированного проектирования учебных планов"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(projects.router, prefix="/projects", tags=["Projects"])
app.include_router(repository.router, prefix="/repository", tags=["Repository"])
app.include_router(kag.router, prefix="/kag", tags=["KAG Engine"])
app.include_router(planner.router, prefix="/planner", tags=["Planner"])
app.include_router(export_api.router, prefix="/export", tags=["Export"])
app.include_router(epvo_api.router, prefix="/epvo", tags=["EPVO"])
app.include_router(git_versions.router, prefix="/git", tags=["Git Versions"])


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
