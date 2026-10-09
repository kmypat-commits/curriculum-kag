from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.plan_build_status import PlanBuildStatus


def test_diagnostic_without_worker_ownership_cannot_emit_into_live_job(monkeypatch):
    from unittest.mock import patch
    from app.api import planner_state
    from app.services.build_events import emit_build_event
    monkeypatch.setattr(planner_state, 'get_build_status', lambda _: {'job_id': 'someone-elses-live-job'})
    token = planner_state._build_owner_token.set(None)
    try:
        with patch('app.database.SessionLocal.begin') as begin:
            emit_build_event(15, 'candidates', {'count': 0})
            begin.assert_not_called()
    finally:
        planner_state._build_owner_token.reset(token)


def test_events_are_durable_sequential_and_cannot_cross_jobs():
    from app.services.build_events import append_event, read_events
    engine = create_engine('sqlite://')
    AuditEvent.__table__.create(engine)
    PlanBuildStatus.__table__.create(engine)
    with Session(engine) as db:
        db.add(PlanBuildStatus(project_version_id=3, state='running', stage='scoring',
                               job_id='current', worker_id='worker'))
        db.commit()
        append_event(db, 3, 'current', 'stage', {'stage': 'scoring'}, worker_id='worker')
        append_event(db, 3, 'current', 'candidates', {'count': 200, 'nodes': []}, worker_id='worker')
        assert append_event(db, 3, 'old', 'selected', {'course_ids': [9]}) is None
        assert append_event(db, 3, 'current', 'selected', {'course_ids': [9]}, worker_id='stale') is None
        db.commit()
        page = read_events(db, 3, 'current', after=0, limit=1)
        assert len(page['events']) == 1 and page['has_more']
        second = read_events(db, 3, 'current', after=page['next_cursor'], limit=10)
        assert second['events'][0]['type'] == 'candidates'
        assert second['events'][0]['sequence'] > page['events'][0]['sequence']
        assert read_events(db, 3, 'old', after=0, limit=10)['events'] == []
