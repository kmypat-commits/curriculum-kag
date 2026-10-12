from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.api import kag
from app.services.generation_capacity import CapacityBusy


def test_busy_scoring_returns_retryable_response_without_starting_model(monkeypatch):
    @contextmanager
    def busy(_engine):
        raise CapacityBusy('occupied')
        yield

    def unexpected_model(*args, **kwargs):
        pytest.fail('Scoring began before resource admission')

    monkeypatch.setattr(kag, 'generation_slot', busy, raising=False)
    monkeypatch.setattr(kag, 'compute_all_matches', unexpected_model)
    with pytest.raises(HTTPException) as error:
        kag._capacity_checked_matches(15, SimpleNamespace(get_bind=lambda: object()))
    assert error.value.status_code == 503
    assert error.value.headers['Retry-After'] == '2'


def test_busy_recompute_does_not_claim_a_running_attempt(monkeypatch):
    from app.api import planner_build
    observed = {'claimed': False}
    @contextmanager
    def busy(_engine):
        raise CapacityBusy('occupied')
        yield
    class Query:
        def filter(self, *args): return self
        def first(self): return SimpleNamespace(id=77)
    class DB:
        def get_bind(self): return object()
        def query(self, *args): return Query()
    def claim(*args, **kwargs):
        observed['claimed'] = True
        return None
    monkeypatch.setattr(planner_build, 'generation_slot', busy, raising=False)
    monkeypatch.setattr(planner_build, '_claim_build_status', claim)
    with pytest.raises(HTTPException) as error:
        planner_build.recompute_matches(77, DB(), SimpleNamespace(id=12))
    assert error.value.status_code == 503
    assert error.value.headers['Retry-After'] == '2'
    assert observed == {'claimed': False}


def test_busy_synchronous_build_does_not_claim_job(monkeypatch):
    from app.api import planner_build
    from app.schemas.planner import PlannerBuildRequest
    observed = {'claimed': False}
    @contextmanager
    def busy(_engine):
        raise CapacityBusy('occupied')
        yield
    def claim(*args, **kwargs):
        observed['claimed'] = True
        return None
    monkeypatch.setattr(planner_build.settings, 'ASYNC_BUILDS', False)
    monkeypatch.setattr(planner_build, 'generation_slot', busy)
    monkeypatch.setattr(planner_build, '_load_program_spec_for_command',
                        lambda *args: ({'constraints': {}}, 'snapshot77'))
    monkeypatch.setattr(planner_build, '_get_build_status', lambda *args: {})
    monkeypatch.setattr(planner_build, '_claim_build_status', claim)
    with pytest.raises(HTTPException) as error:
        planner_build.build_plan(77, PlannerBuildRequest(variants='A'),
                                 SimpleNamespace(get_bind=lambda: object()),
                                 SimpleNamespace(id=12), None)
    assert error.value.status_code == 503
    assert observed == {'claimed': False}
