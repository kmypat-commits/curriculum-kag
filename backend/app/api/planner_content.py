"""Owner-scoped local content reports and resumable build telemetry."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.plan import Plan, PlanItem
from app.models.user import User
from app.services.access import require_version_access
from app.services.auth import get_current_user
from app.services.rbac import check_permission
from app.services.content_evaluation import evaluate_schedule, persisted_schedule
from app.services.build_events import read_events

router = APIRouter()


def _report(version_id, plan_id, db, actor):
    version = require_version_access(db, actor, version_id)
    if not check_permission(actor, 'planner', 'read'):
        raise HTTPException(403, 'Недостаточно прав')
    plan = db.query(Plan).filter(Plan.id == plan_id, Plan.project_version_id == version_id).first()
    if not plan:
        raise HTTPException(404, 'План не найден')
    items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
    report = evaluate_schedule(version, db, persisted_schedule(plan, items))
    saved = (plan.metrics_json or {}).get('content_evaluation')
    return plan, {'plan_id': plan.id, 'report': report, 'saved_report': saved,
                  'stale': not saved or saved.get('snapshot_hash') != report['snapshot_hash']}


@router.get('/{project_version_id}/content-evaluation')
def get_content_evaluation(project_version_id: int, plan_id: int = Query(..., gt=0),
                           db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return _report(project_version_id, plan_id, db, actor)[1]


@router.post('/{project_version_id}/content-evaluation')
def refresh_content_evaluation(project_version_id: int, plan_id: int = Query(..., gt=0),
                               db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    if not check_permission(actor, 'planner', 'write'):
        raise HTTPException(403, 'Недостаточно прав')
    plan, response = _report(project_version_id, plan_id, db, actor)
    plan.metrics_json = {**(plan.metrics_json or {}), 'content_evaluation': response['report']}
    db.commit()
    return {**response, 'saved_report': response['report'], 'stale': False}


@router.get('/{project_version_id}/build-events')
def get_build_events(project_version_id: int, job_id: str = Query(..., min_length=1, max_length=100),
                     after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                     db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    require_version_access(db, actor, project_version_id)
    if not check_permission(actor, 'planner', 'read'):
        raise HTTPException(403, 'Недостаточно прав')
    return read_events(db, project_version_id, job_id, after=after, limit=limit)
