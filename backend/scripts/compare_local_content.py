"""Compare both advisory modes in one repeatable-read catalogue snapshot.

No plans are persisted and all temporary requirement/GOSO changes roll back.
This is an engineering comparison, not an academic content acceptance.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from app.database import SessionLocal
import app.models
from app.models.project import ProjectVersion
from app.planner.joint_planner import build_verified_joint_schedule
from app.planner.joint_contract import PlanningFailure
from app.planner.content_evaluation import canonical_hash, EVALUATOR_VERSION
from app.services.content_evaluation import evaluate_schedule, profile_for_version


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('refusing to overwrite comparison evidence')
    evidence = {'version_id': args.version, 'evaluator_version': EVALUATOR_VERSION,
                'code_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, encoding='utf-8').strip(),
                'working_tree_patch_sha256': canonical_hash(subprocess.check_output(['git', 'diff'], text=True, encoding='utf-8')),
                'local_module_hashes': {str(path.relative_to(Path(__file__).resolve().parents[1])): canonical_hash(path.read_text(encoding='utf-8'))
                    for path in [Path(__file__).resolve().parents[1] / 'app/planner/content_evaluation.py',
                                 Path(__file__).resolve().parents[1] / 'app/services/content_evaluation.py']},
                'modes': {}, 'published': False}
    with SessionLocal() as db:
        db.connection(execution_options={'isolation_level': 'REPEATABLE READ'})
        evidence['database_snapshot'] = db.execute(text('SELECT txid_current_snapshot()::text')).scalar()
        version = db.get(ProjectVersion, args.version)
        if version is None:
            parser.error('version not found')
        evidence['profile'] = profile_for_version(version)
        evidence['input_hash'] = canonical_hash({'profile': evidence['profile'], 'constraints': version.project.constraints_json})
        for mode in ('shadow', 'prioritise'):
            started = time.perf_counter()
            with db.begin_nested() as temporary:
                version.project.constraints_json = {**(version.project.constraints_json or {}), 'content_evaluation_mode': mode}
                try:
                    schedule, joint = build_verified_joint_schedule(version, db, 'A')
                    result = {'status': 'verified', 'schedule': schedule,
                              'evaluation': evaluate_schedule(version, db, schedule),
                              'verification': joint['verification'], 'planner': joint['planner']}
                except PlanningFailure as exc:
                    result = {'status': 'failed', 'diagnostic': exc.diagnostic()}
                evidence['modes'][mode] = {**result, 'elapsed_seconds': round(time.perf_counter() - started, 3)}
                temporary.rollback()
        db.rollback()
    evidence['canonical_sha256'] = canonical_hash(evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({mode: {'status': row['status'], 'elapsed_seconds': row['elapsed_seconds'],
                            'indicators': row.get('evaluation', {}).get('indicators')}
                      for mode, row in evidence['modes'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
