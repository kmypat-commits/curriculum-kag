"""Durable bounded telemetry in the existing audit store; no migration required."""
from datetime import datetime, timezone

from app.models.audit import AuditEvent
from app.models.plan_build_status import PlanBuildStatus

ACTION = 'planner_build_event'


def append_event(db, version_id, job_id, kind, data, *, worker_id=None):
    if not job_id:
        return None
    # Serialize against job replacement: stale workers cannot append to a retry.
    row = db.query(PlanBuildStatus).filter(
        PlanBuildStatus.project_version_id == version_id).with_for_update().first()
    if not row or row.job_id != job_id or (worker_id and row.worker_id != worker_id):
        return None
    event = AuditEvent(action=ACTION, entity_type='project_version', entity_id=version_id,
                       details_json={'job_id': job_id, 'type': kind, 'data': data},
                       timestamp=datetime.now(timezone.utc))
    db.add(event)
    db.flush()
    return event.id


def read_events(db, version_id, job_id, *, after, limit):
    current = db.query(PlanBuildStatus).filter(PlanBuildStatus.project_version_id == version_id).first()
    rows = db.query(AuditEvent).filter(
        AuditEvent.action == ACTION, AuditEvent.entity_type == 'project_version',
        AuditEvent.entity_id == version_id, AuditEvent.id > after,
        AuditEvent.details_json['job_id'].as_string() == job_id,
    ).order_by(AuditEvent.id.asc()).limit(limit + 1).all()
    events = [{'sequence': row.id, 'job_id': job_id,
               'timestamp': row.timestamp.isoformat(), **row.details_json} for row in rows[:limit]]
    return {'job_id': job_id, 'events': events,
            'next_cursor': events[-1]['sequence'] if events else after,
            'has_more': len(rows) > limit,
            'state': current.state if current and current.job_id == job_id else 'superseded'}


def emit_build_event(version_id, kind, data):
    from app.api.planner_state import get_build_status, _build_owner_token
    from app.database import SessionLocal
    from sqlalchemy.exc import SQLAlchemyError
    owner = _build_owner_token.get()
    if not owner:
        return  # CLI diagnostics/tests are not workers of a published UI job.
    status = get_build_status(version_id)
    if not status.get('job_id'):
        return
    try:
        with SessionLocal.begin() as db:
            append_event(db, version_id, status['job_id'], kind, data,
                         worker_id=owner)
    except SQLAlchemyError:
        import logging
        logging.getLogger(__name__).exception('Could not persist build telemetry')
