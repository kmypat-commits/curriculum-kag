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


def test_fresh_a_does_not_present_old_excluded_b_as_current_variant():
    """A partial A rebuild must not make an old excluded B look current."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.api.planner_coverage import get_variants
    from app.database import Base
    from app.models.course import Course
    from app.models.plan import Plan, PlanItem
    from app.models.project import Project, ProjectVersion

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            version = ProjectVersion(
                version_number=1,
                project=Project(title="Test", domain1="IT", domain2="",
                                constraints_json={"excluded_course_ids": [1158]}),
            )
            db.add(version)
            db.add_all([
                Course(id=1158, course_id="EPVO-8087", title="Биоинформатика",
                       domain="IT", credits=3),
                Course(id=1159, course_id="EPVO-8088", title="Информатика",
                       domain="IT", credits=3),
            ])
            db.flush()
            old_b = Plan(project_version_id=version.id, variant_type="B", metrics_json={})
            fresh_a = Plan(project_version_id=version.id, variant_type="A",
                           is_active=1, metrics_json={})
            db.add_all([old_b, fresh_a])
            db.flush()
            db.add_all([
                PlanItem(plan_id=old_b.id, semester=1, course_id=1158, credits=3),
                PlanItem(plan_id=fresh_a.id, semester=1, course_id=1159, credits=3),
            ])
            db.commit()

            response = get_variants(version.id, False, False, db, SimpleNamespace(id=1))
            assert [row["variant_type"] for row in response] == ["A"]
            assert db.get(Plan, old_b.id) is not None
    finally:
        engine.dispose()
