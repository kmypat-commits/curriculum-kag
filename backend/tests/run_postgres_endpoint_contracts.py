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
    from app.models.user import User
    from app.services.auth import create_access_token
    email = f"endpoint-contract-{uuid.uuid4().hex}@test.local"
    with SessionLocal() as db:
        user = User(email=email, full_name="Endpoint contract", hashed_password="unused", is_active=1)
        db.add(user)
        db.flush()
        project = Project(title="Endpoint contract", domain1="ICT", domain2="", created_by=user.id, constraints_json={})
        db.add(project)
        db.flush()
        version = ProjectVersion(project_id=project.id, version_number=1, status="draft")
        db.add(version)
        db.commit()
        version_id = version.id

    headers = {"Authorization": f"Bearer {create_access_token({'sub': email})}"}
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
    print(f"PostgreSQL endpoint contracts passed: {len(checks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
