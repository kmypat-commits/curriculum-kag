"""Run authenticated planner endpoint contracts against a dedicated PostgreSQL DB.

Usage (from backend):
  $env:CURRICULUM_KAG_TEST_DATABASE_URL='postgresql://.../curriculum_kag_endpoint_test'
  python tests/run_postgres_endpoint_contracts.py
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

# Support both `python backend/tests/...` and `python tests/...` invocations.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.engine import make_url


def main() -> int:
    url = os.environ.get("CURRICULUM_KAG_TEST_DATABASE_URL", "")
    if not url or not make_url(url).database.endswith("_test"):
        raise SystemExit("Use a dedicated PostgreSQL database whose name ends in _test.")
    os.environ["DATABASE_URL"] = url

    # Importing the application creates PostgreSQL indexes.  A clean CI
    # database has no tables yet, so migrate before importing app.main.
    from alembic import command
    from alembic.config import Config
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")

    from fastapi.testclient import TestClient
    from app.database import SessionLocal
    from app.main import app
    from app.models.project import Project, ProjectVersion
    from app.models.user import User, Role
    from app.services.auth import create_access_token
    suffix = uuid.uuid4().hex
    email = f"endpoint-contract-owner-{suffix}@test.local"
    other_email = f"endpoint-contract-other-{suffix}@test.local"
    admin_email = f"endpoint-contract-admin-{suffix}@test.local"
    with SessionLocal() as db:
        def role(name: str) -> Role:
            item = db.query(Role).filter(Role.name == name).first()
            if item:
                return item
            item = Role(name=name, description="Endpoint contract role")
            db.add(item)
            db.flush()
            return item

        owner = User(email=email, full_name="Endpoint owner", hashed_password="unused", is_active=1)
        other = User(email=other_email, full_name="Endpoint other", hashed_password="unused", is_active=1)
        admin = User(email=admin_email, full_name="Endpoint admin", hashed_password="unused", is_active=1)
        db.add_all([owner, other, admin])
        db.flush()
        owner.roles = [role("analyst")]
        other.roles = [role("analyst")]
        admin.roles = [role("admin")]
        db.flush()
        project = Project(title="Endpoint contract", domain1="ICT", domain2="", created_by=owner.id, constraints_json={})
        db.add(project)
        db.flush()
        version = ProjectVersion(project_id=project.id, version_number=1, status="draft")
        db.add(version)
        db.commit()
        project_id = project.id
        version_id = version.id

    def auth_headers(subject: str) -> dict[str, str]:
        # Bearer authentication is the CLI transport and the application
        # deliberately requires an explicit token_use claim.  Keep this
        # smoke test aligned with the production token contract instead of
        # accidentally exercising an invalid browser-shaped token.
        return {
            "Authorization": f"Bearer {create_access_token({'sub': subject, 'token_use': 'cli', 'token_version': 0})}"
        }

    headers = auth_headers(email)
    other_headers = auth_headers(other_email)
    admin_headers = auth_headers(admin_email)
    with TestClient(app) as client:
        checks = {
            f"/planner/{version_id}/build-status": {200},
            f"/planner/{version_id}/variants": {200},
            f"/planner/{version_id}/variants?include_explanations=true": {200},
            f"/planner/version/{version_id}/graph": {404},
            f"/planner/{version_id}/evaluation": {200, 404},
            "/planner/syllabus/course/999999": {404},
        }
        for path, expected in checks.items():
            response = client.get(path, headers=headers)
            assert response.status_code in expected, (path, response.status_code, response.text[:300])
        # Real object-level checks: the other user must not learn that the
        # project/version exists, while admin retains operational access.
        assert client.get(f"/projects/{project_id}", headers=headers).status_code == 200
        assert client.get(f"/projects/{project_id}", headers=other_headers).status_code == 404
        assert client.get(f"/projects/{project_id}", headers=admin_headers).status_code == 200
        assert client.get("/projects", headers=other_headers).json() == []
        assert any(item["id"] == project_id for item in client.get("/projects", headers=admin_headers).json())
        assert client.get(f"/planner/{version_id}/build-status", headers=other_headers).status_code == 404
        assert client.get(f"/planner/{version_id}/build-status", headers=admin_headers).status_code == 200
    print(f"PostgreSQL endpoint contracts passed: {len(checks)} + 8 owner/other/admin checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
