import importlib.util
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from app.services.generation_capacity import CapacityBusy


def test_one_shot_busy_returns_retryable_without_querying_owner_or_model(monkeypatch):
    spec = importlib.util.spec_from_file_location('worker_one_shot_capacity',
        Path(__file__).parents[1] / 'scripts/run_planner_build_worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    observed = {'queried': False, 'closed': False}
    class DB:
        def get_bind(self): return object()
        def query(self, *args):
            observed['queried'] = True
            raise RuntimeError('owner lookup must not begin while busy')
        def close(self): observed['closed'] = True
    @contextmanager
    def occupied(_engine):
        raise CapacityBusy('occupied')
        yield
    monkeypatch.setattr(worker, 'SessionLocal', DB)
    monkeypatch.setattr(worker, 'generation_slot', occupied)
    result = worker._build_one(version_id=77, user_id=12, variants='A',
                               job_id='job77', idempotency_key=None)
    assert result == 2
    assert observed == {'queried': False, 'closed': True}


def test_busy_worker_leaves_job_queued_without_starting_model(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('worker_capacity_test',
        Path(__file__).parents[1] / 'scripts/run_planner_build_worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    state = {'state': 'queued', 'model_started': False}
    row = SimpleNamespace(id=1, project_version_id=77, job_id='job77',
                          requested_by_user_id=12, cancel_requested=0,
                          payload_json={'job_id': 'job77', 'requested_by_user_id': 12,
                                        'requested_variants': 'A'})
    class Query:
        def filter(self, *args): return self
        def order_by(self, *args): return self
        def with_for_update(self, **kwargs): return self
        def limit(self, *args): return self
        def all(self): return [row]
    class DB:
        def query(self, *args): return Query()
        def commit(self): pass
        def close(self): pass
        def get_bind(self): return object()
    @contextmanager
    def occupied(_engine):
        raise CapacityBusy('occupied by another user')
        yield
    def claim(*args, **kwargs):
        state['state'] = 'running'
        return {'state': 'running'}
    def model(**kwargs):
        state['model_started'] = True
        worker._shutdown = True
        return 0
    def stop_polling(_seconds):
        worker._shutdown = True
    monkeypatch.setattr(worker, 'SessionLocal', DB)
    monkeypatch.setattr(worker, 'generation_slot', occupied, raising=False)
    monkeypatch.setattr(worker, 'claim_build_status', claim)
    monkeypatch.setattr(worker, '_build_one', model)
    monkeypatch.setattr(worker.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(worker.time, 'sleep', stop_polling)
    monkeypatch.setattr(worker, 'HEARTBEAT_FILE', tmp_path / 'heartbeat')
    worker._run_daemon(.5, 1)
    assert state == {'state': 'queued', 'model_started': False}


def test_scoped_daemon_never_claims_jobs_outside_pilot(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models.plan_build_status import PlanBuildStatus

    spec = importlib.util.spec_from_file_location('worker_scoped_test',
        Path(__file__).parents[1] / 'scripts/run_planner_build_worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for index, job in enumerate(['foreign-old-job', 'pilot-job'], 1):
            db.add(PlanBuildStatus(project_version_id=index, state='queued',
                job_id=job,
                payload_json={'job_id': job, 'requested_by_user_id': 1,
                              'requested_variants': 'A'}))
        db.commit()
    claimed = []
    def consume(db, row, status, **kwargs):
        claimed.append(row.job_id)
        worker._shutdown = True
        return 0
    monkeypatch.setattr(worker, 'SessionLocal', factory)
    monkeypatch.setattr(worker, '_claim_and_build', consume)
    monkeypatch.setattr(worker.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(worker, 'HEARTBEAT_FILE', tmp_path / 'heartbeat')
    try:
        worker._run_daemon(.01, 2, job_ids=('pilot-job',),
                           heartbeat_file=tmp_path / 'pilot-heartbeat')
        assert claimed == ['pilot-job']
        assert (tmp_path / 'pilot-heartbeat').exists()
        assert not (tmp_path / 'heartbeat').exists()
        with factory() as db:
            assert db.query(PlanBuildStatus).filter_by(job_id='foreign-old-job').one().state == 'queued'
    finally:
        engine.dispose()
