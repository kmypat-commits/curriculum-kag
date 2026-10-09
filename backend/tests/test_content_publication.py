from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.project import Project, ProjectVersion
from app.models.plan import Plan
from app.planner.plan_result_assembly import persist_plan_result


def test_direct_scheduler_publication_freezes_local_content_report():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        version = ProjectVersion(version_number=1, project=Project(
            title='История', domain1='История', domain2='', goal='История общества', constraints_json={}))
        db.add(version)
        db.flush()
        result = persist_plan_result(db=db, project_version_id=version.id,
            variant_type='A', schedule={1: []}, metrics={}, verification={}, commit=False)
        saved = db.get(Plan, result['plan_id']).metrics_json
        assert saved['content_evaluation']['evaluator_version'].startswith('local-content-')
        assert saved['content_evaluation']['snapshot_hash']
        assert result['metrics']['content_evaluation'] == saved['content_evaluation']
    engine.dispose()


def test_disposable_cohort_freezes_content_evidence_before_plan_cleanup():
    from scripts.audit_cross_level_generation import freeze_content_report
    metrics = {'content_evaluation': {'evaluator_version': 'local-content-1.1',
                                     'snapshot_hash': 'verified-source', 'courses': [{'course_id': 7}]}}
    evidence = freeze_content_report(metrics)
    metrics['content_evaluation']['courses'].clear()
    assert evidence['courses'] == [{'course_id': 7}]
    assert freeze_content_report({}) is None
