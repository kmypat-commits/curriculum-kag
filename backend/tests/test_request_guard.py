from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.main import CSRFMiddleware, RequestGuardMiddleware, SecurityHeadersMiddleware


def test_expensive_global_operations_are_rate_limited(monkeypatch):
    app = FastAPI()
    app.add_middleware(RequestGuardMiddleware)

    @app.post("/projects/suggestions")
    def suggestions():
        return {"ok": True}

    monkeypatch.setattr(settings, "RATE_LIMIT_EXPENSIVE_PER_TEN_MINUTES", 1)
    RequestGuardMiddleware._events.clear()
    client = TestClient(app)

    assert client.post("/projects/suggestions").status_code == 200
    limited = client.post("/projects/suggestions")
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "600"


def test_build_limit_allows_a_normal_methodist_review_session(monkeypatch):
    """A user must be able to retry and compare plans before being throttled."""
    app = FastAPI()
    app.add_middleware(RequestGuardMiddleware)

    @app.post("/planner/15/build")
    def build():
        return {"ok": True}

    monkeypatch.setattr(settings, "RATE_LIMIT_BUILD_PER_TEN_MINUTES", 8)
    RequestGuardMiddleware._events.clear()
    client = TestClient(app)

    for _ in range(8):
        assert client.post("/planner/15/build").status_code == 200
    assert client.post("/planner/15/build").status_code == 429


def test_production_security_headers_are_present(monkeypatch):
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    def health():
        return {"ok": True}

    monkeypatch.setattr(settings, "APP_ENV", "production")
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" in response.headers
    assert "Content-Security-Policy" in response.headers


def test_cookie_authenticated_write_requires_csrf_header():
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post("/projects")
    def create_project():
        return {"ok": True}

    client = TestClient(app)
    client.cookies.set("access_token", "opaque")
    response = client.post("/projects")

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF validation failed"
