"""Freeze and review persisted schedules without regenerating or changing them."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import SessionLocal
import app.models
from app.models.plan import Plan, PlanItem
from app.models.project import ProjectVersion
from app.models.course import Course
from app.planner.content_evaluation import canonical_hash, course_record, EVALUATOR_VERSION
from app.services.content_evaluation import evaluate_schedule, persisted_schedule, profile_for_version


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--versions', nargs='+', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('refusing to overwrite evidence')
    started = time.perf_counter()
    cases = []
    with SessionLocal() as db:
        # A single consistent snapshot, including source records and graph.
        if db.bind.dialect.name == 'postgresql':
            db.connection(execution_options={'isolation_level': 'REPEATABLE READ'})
        for vid in args.versions:
            version = db.query(ProjectVersion).filter(ProjectVersion.id == vid).first()
            if not version:
                cases.append({'version_id': vid, 'status': 'missing_version'})
                continue
            plan = db.query(Plan).filter(Plan.project_version_id == vid, Plan.variant_type == 'A').order_by(Plan.id.desc()).first()
            if not plan:
                cases.append({'version_id': vid, 'status': 'missing_plan'})
                continue
            rows = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
            schedule = persisted_schedule(plan, rows)
            report = evaluate_schedule(version, db, schedule)
            ids = [item.course_id for item in rows if item.course_id is not None]
            courses = db.query(Course).filter(Course.id.in_(ids)).all()
            cases.append({'version_id': vid, 'plan_id': plan.id, 'status': 'reviewed',
                          'profile': profile_for_version(version), 'schedule': schedule,
                          'course_snapshot': [course_record(c) for c in courses],
                          'evaluation': report})
        db.rollback()
    evidence = {'created_at': datetime.now(timezone.utc).isoformat(), 'evaluator_version': EVALUATOR_VERSION,
                'elapsed_seconds': round(time.perf_counter() - started, 3), 'cases': cases,
                'purpose': 'local advisory review of saved plans; not new generation or expert acceptance'}
    evidence['canonical_sha256'] = canonical_hash(evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'reviewed': sum(c['status'] == 'reviewed' for c in cases),
                      'requested': len(cases), 'elapsed_seconds': evidence['elapsed_seconds'],
                      'indicators': [{'version': c['version_id'], **c['evaluation']['indicators']}
                                     for c in cases if 'evaluation' in c]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
