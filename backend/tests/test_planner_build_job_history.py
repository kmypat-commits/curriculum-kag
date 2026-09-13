"""Durable job/attempt history contract on a disposable real SQLAlchemy DB."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import planner_state
from app.database import Base
from app.models.planner_build_job import PlannerBuildAttempt, PlannerBuildJob


def test_job_identity_and_attempt_history_survive_queued_to_running_to_complete(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(planner_state, "SessionLocal", factory)
    planner_state.plan_build_status.clear()

    queued = planner_state.claim_build_status(
        7001,
        state="queued",
        stage="queued",
        progress=0,
        job_id="build-history-contract",
        request_hash="b" * 64,
        idempotency_key="request-key",
    )
    assert queued is not None
    assert queued["job_id"] == "build-history-contract"

    with factory() as db:
        job = db.query(PlannerBuildJob).filter_by(public_id="build-history-contract").one()
        assert job.state == "queued"
        assert job.request_hash == "b" * 64
        assert db.query(PlannerBuildAttempt).count() == 0

    running = planner_state.claim_build_status(7001, state="running", stage="matching", progress=5)
    assert running is not None
    assert running["job_id"] == "build-history-contract"
    assert running["worker_id"]

    with factory() as db:
        job = db.query(PlannerBuildJob).filter_by(public_id="build-history-contract").one()
        attempt = db.query(PlannerBuildAttempt).filter_by(job_id=job.id).one()
        assert job.state == "running"
        assert attempt.ordinal == 1
        assert attempt.owner_token == running["worker_id"]
        assert attempt.state == "running"

    planner_state.set_build_status(7001, state="complete", stage="complete", progress=100)
    with factory() as db:
        job = db.query(PlannerBuildJob).filter_by(public_id="build-history-contract").one()
        attempt = db.query(PlannerBuildAttempt).filter_by(job_id=job.id).one()
        assert job.state == "complete"
        assert job.finished_at is not None
        assert attempt.state == "complete"
        assert attempt.finished_at is not None
        assert attempt.lease_expires_at is None
