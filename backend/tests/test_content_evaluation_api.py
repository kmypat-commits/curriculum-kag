from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.services.auth import get_current_user


@pytest.mark.parametrize('actor_id,role,expected', [(7, 'methodist', 200), (8, 'methodist', 404)])
def test_content_report_enforces_owner_and_detects_changed_snapshot(actor_id, role, expected):
    from app.api.planner_content import router
    from app.models.project import ProjectVersion
    from app.models.plan import Plan, PlanItem
    version = SimpleNamespace(id=3, project=SimpleNamespace(created_by=7))
    plan = SimpleNamespace(id=9, project_version_id=3,
                           metrics_json={'content_evaluation': {'snapshot_hash': 'old'}})

    class Query:
        def __init__(self, value): self.value = value
        def filter(self, *args): return self
        def first(self): return self.value
        def all(self): return self.value
    class DB:
        def query(self, model):
            return Query({ProjectVersion: version, Plan: plan, PlanItem: []}[model])
    actor = SimpleNamespace(id=actor_id, roles=[SimpleNamespace(name=role)])
    app = FastAPI()
    app.include_router(router, prefix='/planner')
    app.dependency_overrides[get_db] = lambda: DB()
    app.dependency_overrides[get_current_user] = lambda: actor
    with patch('app.api.planner_content.evaluate_schedule', return_value={'snapshot_hash': 'new'}):
        response = TestClient(app).get('/planner/3/content-evaluation?plan_id=9')
    assert response.status_code == expected
    if expected == 200:
        assert response.json()['stale'] is True
        assert response.json()['report']['snapshot_hash'] == 'new'
