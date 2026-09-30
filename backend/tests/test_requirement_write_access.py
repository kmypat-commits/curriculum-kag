"""The real constraints route must require both ownership and write permission."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.projects import router
from app.database import get_db
from app.services.auth import get_current_user


@pytest.mark.parametrize("user_id,role,status", [
    (7, "analyst", 403), (7, "guest", 403),
    (7, "methodist", 200), (8, "methodist", 404), (9, "admin", 200),
])
def test_constraints_write_access_and_no_mutation_on_denial(user_id, role, status):
    original = {"retained": "published-input"}
    project = SimpleNamespace(id=4, created_by=7, constraints_json=deepcopy(original))

    class DB:
        commits = 0

        def query(self, model):
            return self

        def filter(self, *args):
            return self

        def first(self):
            return project

        def commit(self):
            self.commits += 1

    db = DB()
    actor = SimpleNamespace(id=user_id, roles=[SimpleNamespace(name=role)])
    app = FastAPI()
    app.include_router(router, prefix="/projects")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    constraints = {
        "education_level": "bachelor", "education_area": "6B06",
        "direction_code": "6B061", "group_code": "B057",
        "program_type": "standard", "instruction_language": "ru",
        "duration_years": 4, "total_semesters": 8,
        "total_credits": 240, "max_credits_per_semester": 30,
        "curriculum_requirements": {"enabled": False},
    }
    response = TestClient(app).patch("/projects/4/constraints", json={"constraints": constraints})
    assert response.status_code == status, response.text
    if status != 200:
        assert db.commits == 0
        assert project.constraints_json == original
    else:
        assert db.commits == 1
        assert project.constraints_json["total_credits"] == 240
        assert project.constraints_json["curriculum_requirements"]["enabled"] is False
