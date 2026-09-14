from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import os
import logging
import time
import secrets
import uuid
import threading
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

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
from app.models import user, project, course, plan, embedding, audit, bridge_module, syllabus, epvo, plan_build_status, rate_limit, planner_draft

logger = logging.getLogger("curriculum.performance")


class RequestGuardMiddleware(BaseHTTPMiddleware):
    """Bound request bodies and rate-limit expensive/authentication endpoints."""

    _lock = threading.Lock()
    _events: dict[tuple[str, str], list[float]] = {}

    @classmethod
    def _shared_bucket_allowed(cls, bucket: str, client_key: str, limit: int, window: int) -> bool | None:
        """Atomically increment a PostgreSQL bucket when shared limiting is enabled."""
        if settings.RATE_LIMIT_BACKEND.lower() not in {"postgres", "postgresql"}:
            return False
        if str(settings.DATABASE_URL).startswith("sqlite"):
            return False
        window_start = int(time.time() // window) * window
        try:
            with engine.begin() as connection:
                dialect = connection.dialect.name
                if dialect == "postgresql":
                    row = connection.execute(text(
                        "INSERT INTO rate_limit_buckets "
                        "(bucket, client_key, window_start, event_count, updated_at) "
                        "VALUES (:bucket, :client_key, :window_start, 1, CURRENT_TIMESTAMP) "
                        "ON CONFLICT (bucket, client_key, window_start) DO UPDATE "
                        "SET event_count = rate_limit_buckets.event_count + 1, "
                        "updated_at = CURRENT_TIMESTAMP "
                        "RETURNING event_count"
                    ), {"bucket": bucket, "client_key": client_key, "window_start": window_start}).scalar_one()
                else:
                    # Keep a conservative fallback for compatible SQL dialects.
                    row = connection.execute(text(
                        "SELECT event_count FROM rate_limit_buckets "
                        "WHERE bucket=:bucket AND client_key=:client_key AND window_start=:window_start"
                    ), {"bucket": bucket, "client_key": client_key, "window_start": window_start}).scalar()
                    if row is None:
                        connection.execute(text(
                            "INSERT INTO rate_limit_buckets "
                            "(bucket, client_key, window_start, event_count, updated_at) "
                            "VALUES (:bucket, :client_key, :window_start, 1, CURRENT_TIMESTAMP)"
                        ), {"bucket": bucket, "client_key": client_key, "window_start": window_start})
                        row = 1
                    else:
                        row = int(row) + 1
                        connection.execute(text(
                            "UPDATE rate_limit_buckets SET event_count=:count, updated_at=CURRENT_TIMESTAMP "
                            "WHERE bucket=:bucket AND client_key=:client_key AND window_start=:window_start"
                        ), {"count": row, "bucket": bucket, "client_key": client_key, "window_start": window_start})
                return int(row) <= limit
        except SQLAlchemyError:
            logger.warning("shared_rate_limit_unavailable bucket=%s", bucket)
            return None

    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.MAX_REQUEST_BYTES:
                    return JSONResponse(status_code=413, content={"detail": "Размер запроса превышает допустимый лимит"})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Некорректный Content-Length"})

        limit, window, bucket = None, None, None
        if request.method == "POST" and request.url.path in {"/auth/login", "/auth/token"}:
            limit, window, bucket = settings.RATE_LIMIT_LOGIN_PER_MINUTE, 60, "login"
        elif request.method == "POST" and request.url.path.startswith("/planner/") and request.url.path.endswith("/build"):
            limit, window, bucket = settings.RATE_LIMIT_BUILD_PER_TEN_MINUTES, 600, "build"
        elif request.method == "POST" and request.url.path in {
            "/projects/suggestions",
            "/repository/generate-courses",
            "/repository/auto-assign-requisites",
            "/kag/graph/build",
            "/kag/system/reindex",
        }:
            limit, window, bucket = settings.RATE_LIMIT_EXPENSIVE_PER_TEN_MINUTES, 600, "expensive"
        if limit is not None:
            key = (bucket, request.client.host if request.client else "unknown")
            shared_backend = settings.RATE_LIMIT_BACKEND.lower() in {"postgres", "postgresql"}
            if shared_backend:
                shared_result = self._shared_bucket_allowed(bucket, key[1], limit, window)
                if shared_result is True:
                    return await call_next(request)
                if shared_result is None:
                    # A database failure must not silently turn a production
                    # limiter into a process-local bypass; fail closed.
                    return JSONResponse(status_code=503, content={"detail": "Сервис временно недоступен"})
                # The shared bucket exists and rejected this request.
                return JSONResponse(status_code=429, content={"detail": "Слишком много запросов; повторите позже"}, headers={"Retry-After": str(window)})
            now = time.monotonic()
            with self._lock:
                recent = [stamp for stamp in self._events.get(key, []) if now - stamp < window]
                if len(recent) >= limit:
                    return JSONResponse(status_code=429, content={"detail": "Слишком много запросов; повторите позже"}, headers={"Retry-After": str(window)})
                recent.append(now)
                self._events[key] = recent
        return await call_next(request)


class SlowRequestMiddleware(BaseHTTPMiddleware):
    """Log only slow API requests; keeps page latency diagnosable without payloads."""

    async def dispatch(self, request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        if response.status_code >= 500:
            logger.error(
                "api_error request_id=%s path=%s method=%s status=%s elapsed_ms=%d",
                getattr(request.state, "request_id", "-"),
                request.url.path,
                request.method,
                response.status_code,
                round(elapsed * 1000),
            )
        if elapsed >= 0.75 and request.url.path not in {"/health", "/"}:
            logger.warning(
                "slow_request request_id=%s path=%s method=%s status=%s elapsed_ms=%d",
                getattr(request.state, "request_id", "-"),
                request.url.path,
                request.method,
                response.status_code,
                round(elapsed * 1000),
            )
        response.headers["Server-Timing"] = f"app;dur={elapsed * 1000:.1f}"
        return response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate a bounded request identifier through logs and responses."""

    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        # Avoid accepting an unbounded attacker-controlled value into logs.
        request_id = request_id[:80]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set baseline browser protections at the API boundary."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if settings.APP_ENV.lower() == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            response.headers.setdefault("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'self'")
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """Require the readable double-submit token for cookie-authenticated writes."""

    async def dispatch(self, request, call_next):
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.url.path not in {"/auth/login", "/auth/token", "/auth/logout"}
            and request.cookies.get("access_token")
        ):
            cookie_token = request.cookies.get("csrf_token")
            header_token = request.headers.get("X-CSRF-Token")
            if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
                return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
        return await call_next(request)

# SQLite remains a local rollback/development mode. PostgreSQL schema changes
# are applied only through Alembic revisions, never implicitly at API startup.
if str(settings.DATABASE_URL).startswith("sqlite"):
    Base.metadata.create_all(bind=engine)
# PostgreSQL schema changes belong to Alembic, not module import.  Running DDL
# here made every backend worker crash when Postgres was still starting.

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Информационная система для автоматизированного проектирования учебных планов",
    docs_url="/docs" if settings.DOCS_ENABLED else None,
    redoc_url="/redoc" if settings.DOCS_ENABLED else None,
    openapi_url="/openapi.json" if settings.DOCS_ENABLED else None,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)
app.add_middleware(CSRFMiddleware)
app.add_middleware(RequestGuardMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(SlowRequestMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# Plan/graph responses can be hundreds of KB of JSON.  Compress only larger
# payloads; small health and metadata responses remain untouched.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(projects.router, prefix="/projects", tags=["Projects"])
app.include_router(repository.router, prefix="/repository", tags=["Repository"])
app.include_router(kag.router, prefix="/kag", tags=["KAG Engine"])
app.include_router(planner.router, prefix="/planner", tags=["Planner"])
app.include_router(export_api.router, prefix="/export", tags=["Export"])
app.include_router(epvo_api.router, prefix="/epvo", tags=["Expert Evidence Repository (legacy API)"])
app.include_router(git_versions.router, prefix="/git", tags=["Git Versions"])


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "expert_evidence_repository": {
            "name": settings.EXPERT_EVIDENCE_REPOSITORY_NAME,
            "slug": settings.EXPERT_EVIDENCE_REPOSITORY_SLUG,
        },
    }


@app.get("/health")
async def health_check():
    database = engine.dialect.name
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "database": database,
            "database_status": "connected",
        }
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "database": database,
                "database_status": "unavailable",
            },
        )
