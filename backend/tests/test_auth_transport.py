import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.api import auth as auth_api
from app.services.auth import decode_access_token


class _Query:
    def filter(self, *_args):
        return self

    def first(self):
        return SimpleNamespace(
            id=7,
            email="owner@example.test",
            full_name="Owner",
            hashed_password="unused",
            is_active=True,
            roles=[],
            cli_token_version=0,
        )


class _DB:
    def query(self, _model):
        return _Query()


def test_browser_login_uses_cookie_only_and_cli_has_explicit_token_endpoint(monkeypatch):
    monkeypatch.setattr(auth_api, "verify_password", lambda _plain, _hashed: True)
    app.dependency_overrides[get_db] = lambda: _DB()
    try:
        client = TestClient(app)

        browser = client.post(
            "/auth/login",
            data={"username": "owner@example.test", "password": "secret"},
        )
        assert browser.status_code == 204
        assert browser.content == b""
        assert "access_token=" in browser.headers.get("set-cookie", "")
        assert "HttpOnly" in browser.headers["set-cookie"]
        assert "csrf_token=" in browser.headers["set-cookie"]

        cli = client.post(
            "/auth/token",
            data={"username": "owner@example.test", "password": "secret"},
        )
        assert cli.status_code == 200
        assert set(cli.json()) == {"access_token", "token_type"}

        assert decode_access_token(cli.json()["access_token"])["token_use"] == "cli"
        assert client.get(
            "/auth/me", headers={"Authorization": f"Bearer {cli.json()['access_token']}"}
        ).status_code == 200
        browser_cookie = browser.cookies.get("access_token")
        assert decode_access_token(browser_cookie)["token_use"] == "browser"
        assert client.get(
            "/auth/me", headers={"Authorization": f"Bearer {browser_cookie}"}
        ).status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_revoke_cli_tokens_increments_version_and_audits():
    user = SimpleNamespace(id=7, cli_token_version=2)

    class DB:
        def __init__(self):
            self.events = []
            self.commits = 0

        def add(self, event):
            self.events.append(event)

        def commit(self):
            self.commits += 1

        def rollback(self):
            raise AssertionError("revoke audit should not fail")

    db = DB()
    asyncio.run(auth_api.revoke_cli_tokens(current_user=user, db=db))
    assert user.cli_token_version == 3
    assert db.commits == 2
    assert [event.action for event in db.events] == ["cli_tokens_revoked"]
