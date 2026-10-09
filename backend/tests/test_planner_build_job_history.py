"""Durable job/attempt history contract on a disposable real SQLAlchemy DB."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextvars import ContextVar

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import planner_state
from app.database import Base
from app.models.planner_build_job import PlannerBuildAttempt, PlannerBuildJob
from app.models.plan_build_status import PlanBuildStatus


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


def test_expired_worker_reclaim_closes_only_previous_attempt_and_keeps_job(monkeypatch):
    """A replacement must not leave a dead execution permanently running."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(planner_state, "SessionLocal", factory)
    planner_state.plan_build_status.clear()
    queued = planner_state.claim_build_status(7002, state="queued", stage="queued",
        job_id="build-crash-history", request_hash="c" * 64)
    assert queued is not None
    first = planner_state.claim_build_status(7002, state="running", stage="matching")
    assert first is not None
    # Simulate a different process, not the permitted same-owner re-entry.
    monkeypatch.setattr(planner_state, "_build_owner_token", ContextVar("replacement_owner", default=None))
    # A healthy current lease must not be stolen or have its attempt closed.
    assert planner_state.claim_build_status(7002, state="running",
        _expected_job_id="build-crash-history") is None
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    with factory.begin() as db:
        db.query(PlanBuildStatus).filter_by(project_version_id=7002).one().lease_expires_at = expired
        db.query(PlannerBuildAttempt).one().lease_expires_at = expired
    recovered = planner_state.claim_build_status(7002, state="running", stage="matching",
        _expected_job_id="build-crash-history")
    assert recovered is not None
    assert recovered["job_id"] == first["job_id"]
    assert recovered["worker_id"] != first["worker_id"]
    with factory() as db:
        job = db.query(PlannerBuildJob).one()
        attempts = db.query(PlannerBuildAttempt).order_by(PlannerBuildAttempt.ordinal).all()
        assert job.state == "running"
        assert len(attempts) == 2
        assert attempts[0].state == "timed_out"
        assert attempts[0].failure_code == "lease_expired"
        assert attempts[0].finished_at is not None
        assert attempts[0].lease_expires_at is None
        assert attempts[1].state == "running"
        assert attempts[1].finished_at is None
    planner_state.set_build_status(7002, state="complete", stage="complete", progress=100)
    with factory() as db:
        assert db.query(PlannerBuildJob).one().state == "complete"
        attempts = db.query(PlannerBuildAttempt).order_by(PlannerBuildAttempt.ordinal).all()
        assert [a.state for a in attempts] == ["timed_out", "complete"]
