"""The persisted-plan read must not execute blocking ORM on ASGI's loop."""
import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.planner_coverage import router
from app.database import get_db
from app.services.auth import get_current_user


def test_variants_database_reads_run_outside_event_loop():
    observations = []

    class Query:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def all(self):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                observations.append("worker")
            else:
                observations.append("event_loop")
            return []

    class DB:
        def query(self, *args):
            return Query()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: DB()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        response = client.get('/1/variants')
    assert response.status_code == 200
    assert response.json() == []
    assert observations and set(observations) == {"worker"}
