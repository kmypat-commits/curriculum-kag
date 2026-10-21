from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.planner_build_job import PlannerBuildAttempt, PlannerBuildJob
from app.models.plan_build_status import PlanBuildStatus
from scripts import recover_interrupted_builds as recovery


@pytest.mark.parametrize('guard', ['expired', 'healthy', 'unknown_lease', 'current_status', 'terminal_status', 'completed_job'])
def test_recover_only_expired_orphans_with_snapshot(tmp_path, guard):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc)
    snapshot = tmp_path / 'before.json'
    with factory.begin() as db:
        job = PlannerBuildJob(public_id='orphan', project_version_id=1,
                              request_hash='hash', queued_at=now,
                              state='complete' if guard == 'completed_job' else 'running')
        db.add(job)
        db.flush()
        lease = now + timedelta(minutes=5) if guard == 'healthy' else now - timedelta(days=1)
        db.add(PlannerBuildAttempt(job_id=job.id, ordinal=1, owner_token='owner',
                                  state='running', started_at=now - timedelta(days=1),
                                  lease_expires_at=None if guard == 'unknown_lease' else lease))
        if guard in {'current_status', 'terminal_status'}:
            db.add(PlanBuildStatus(project_version_id=1, job_id='orphan',
                                   state='running' if guard == 'current_status' else 'timed_out'))
    with factory.begin() as db:
        count = recovery.recover_expired_orphans(db, snapshot, now=now)
    with factory() as db:
        assert count == (1 if guard in {'expired', 'terminal_status', 'completed_job'} else 0)
        expected_state = 'complete' if guard == 'completed_job' else ('timed_out' if count else 'running')
        assert db.query(PlannerBuildJob).one().state == expected_state
        attempt = db.query(PlannerBuildAttempt).one()
        assert attempt.state == ('timed_out' if count else 'running')
        assert snapshot.exists() == bool(count)
        if count:
            import json
            saved = json.loads(snapshot.read_text(encoding='utf-8'))
            assert saved['jobs'][0]['state'] == ('complete' if guard == 'completed_job' else 'running')
            assert saved['attempts'][0]['owner_token'] == 'owner'
            assert attempt.failure_code == 'lease_expired'
            assert attempt.lease_expires_at is None


def test_existing_snapshot_prevents_database_change(tmp_path):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc)
    snapshot = tmp_path / 'before.json'
    snapshot.write_text('keep', encoding='utf-8')
    with factory.begin() as db:
        job = PlannerBuildJob(public_id='orphan', project_version_id=1,
                              request_hash='hash', queued_at=now, state='running')
        db.add(job)
        db.flush()
        db.add(PlannerBuildAttempt(job_id=job.id, ordinal=1, owner_token='owner',
                                  state='running', started_at=now,
                                  lease_expires_at=now - timedelta(days=1)))
    with pytest.raises(FileExistsError), factory.begin() as db:
        recovery.recover_expired_orphans(db, snapshot, now=now)
    with factory() as db:
        assert db.query(PlannerBuildJob).one().state == 'running'
    assert snapshot.read_text(encoding='utf-8') == 'keep'
