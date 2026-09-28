"""The joint planner must not publish an unverified replacement."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.planner.joint_contract import PlanningFailure


@pytest.mark.parametrize("variant_type", ["A", "B", "C"])
def test_joint_planner_never_accepts_excluded_course(variant_type, monkeypatch):
    from app.planner import joint_planner
    from app.planner.joint_contract import PlanningResult

    version = SimpleNamespace(
        id=15, project=SimpleNamespace(
            domain1="IT", domain2="", constraints_json={"excluded_course_ids": [1158]}),
        learning_outcomes=[],
    )
    schedule = {1: [{"course_id": 1158, "credits": 5, "domain": "IT"}]}
    monkeypatch.setattr(joint_planner, "FRONTIER_LIMITS", (1,))
    monkeypatch.setattr(joint_planner, "MAX_VERIFIER_ATTEMPTS_PER_FRONTIER", 1)
    monkeypatch.setattr(joint_planner, "build_joint_frontier",
                        lambda *_args, **_kwargs: SimpleNamespace(
                            frontier_truncated=False, exclusions={}, candidates=(),
                            fixed_schedule={}, target_credits=5, domain_minima=()))
    monkeypatch.setattr(joint_planner, "solve_joint",
                        lambda *_args, **_kwargs: PlanningResult(
                            schedule=schedule, selected_course_ids=frozenset({1158}),
                            objective=1.0, solver_seconds=0.01))
    monkeypatch.setattr(joint_planner, "audit_final_course_admission",
                        lambda *_args, **_kwargs: {"passed": True, "violations": []})
    monkeypatch.setattr(joint_planner, "verify_curriculum_plan",
                        lambda *_args, **_kwargs: {"feasible": True, "quality_passed": True})
    monkeypatch.setattr(joint_planner, "project_domain_terms", lambda *_args: ("IT",))
    monkeypatch.setattr(joint_planner, "audit_final_schedule_boundary",
                        lambda *_args, **_kwargs: {
                            "invalid_domain_courses": [], "admission": {"passed": True}})

    with pytest.raises(PlanningFailure) as exc:
        joint_planner.build_verified_joint_schedule(version, MagicMock(), variant_type)
    assert exc.value.status == "excluded_course_selected"
    assert exc.value.details["course_ids"] == [1158]


@pytest.mark.parametrize("variant_type", ["A", "B", "C"])
def test_joint_planner_never_accepts_missing_methodist_required_course(variant_type, monkeypatch):
    from app.planner import joint_planner
    from app.planner.joint_contract import PlanningResult

    version = SimpleNamespace(
        id=15, project=SimpleNamespace(domain1="IT", domain2="", constraints_json={
            "curriculum_requirements": {"enabled": True, "required_course_ids": [2]},
        }), learning_outcomes=[],
    )
    schedule = {1: [{"course_id": 1, "credits": 5, "domain": "IT"}]}
    monkeypatch.setattr(joint_planner, "FRONTIER_LIMITS", (1,))
    monkeypatch.setattr(joint_planner, "MAX_VERIFIER_ATTEMPTS_PER_FRONTIER", 1)
    monkeypatch.setattr(joint_planner, "build_joint_frontier",
                        lambda *_args, **_kwargs: SimpleNamespace(
                            frontier_truncated=False, exclusions={}, candidates=(),
                            fixed_schedule={}, target_credits=5, domain_minima=()))
    monkeypatch.setattr(joint_planner, "solve_joint",
                        lambda *_args, **_kwargs: PlanningResult(
                            schedule=schedule, selected_course_ids=frozenset({1}),
                            objective=1.0, solver_seconds=0.01))
    monkeypatch.setattr(joint_planner, "audit_final_course_admission",
                        lambda *_args, **_kwargs: {"passed": True, "violations": []})
    monkeypatch.setattr(joint_planner, "verify_curriculum_plan",
                        lambda *_args, **_kwargs: {"feasible": True, "quality_passed": True})
    monkeypatch.setattr(joint_planner, "project_domain_terms", lambda *_args: ("IT",))
    monkeypatch.setattr(joint_planner, "audit_final_schedule_boundary",
                        lambda *_args, **_kwargs: {
                            "invalid_domain_courses": [], "admission": {"passed": True}})

    with pytest.raises(PlanningFailure) as exc:
        joint_planner.build_verified_joint_schedule(version, MagicMock(), variant_type)
    assert exc.value.status == "required_requirements_rejected"
    assert exc.value.details["required_courses"]["missing"] == [2]


def test_final_core_boundary_requires_current_server_evidence_for_block():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.course import Course
    from app.planner.core_evidence import create_confirmation
    from app.planner.joint_planner import _audit_core_requirement_boundary
    from app.schemas.curriculum_requirements import CurriculumRequirements

    block = {"id": "wood", "title": "Деревообработка", "description": "Обработка древесины",
             "requirement": "required", "accepted_course_ids": [17], "min_courses": 1,
             "min_credits": 5}
    requirements = CurriculumRequirements(enabled=True, core_blocks=[block]).model_dump()
    block = requirements["core_blocks"][0]
    course = Course(id=17, course_id="EPVO-17", title="Технология деревообработки",
                    domain="Производство", credits=5, language="ru",
                    description="Проектирование изделий из древесины")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Course.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(Course.__table__.insert(), {
            "id": 17, "course_id": course.course_id, "title": course.title,
            "domain": course.domain, "credits": course.credits,
            "language": course.language, "description": course.description,
        })
    version = SimpleNamespace(id=3, project=SimpleNamespace(constraints_json={
        "curriculum_requirements": requirements,
    }))
    schedule = {1: [{"course_id": 17, "credits": 5}]}
    with Session(engine) as db:
        unconfirmed = _audit_core_requirement_boundary(version, db, schedule)
        assert not unconfirmed["passed"]
        assert unconfirmed["core_coverage"][0]["status"] == "unconfirmed"

        record = create_confirmation(block, course, source_field="description",
                                     excerpt="изделий из древесины", actor_user_id=7,
                                     project_version_id=3, rationale="Проверено")
        version.project.constraints_json["curriculum_confirmations"] = [record]
        confirmed = _audit_core_requirement_boundary(version, db, schedule)
        assert confirmed["passed"]
        assert confirmed["core_coverage"][0]["selected_course_ids"] == [17]


def test_joint_planner_rejects_verifier_disagreement_without_persistence(monkeypatch):
    from app.planner import joint_planner
    from app.planner.joint_contract import PlanningResult

    version = SimpleNamespace(
        id=9, project=SimpleNamespace(
            domain1="IT", domain2="", constraints_json={"total_semesters": 1}),
        learning_outcomes=[],
    )
    db = MagicMock()
    schedule = {1: [{"course_id": 3, "credits": 5, "domain": "IT"}]}
    monkeypatch.setattr(joint_planner, "build_joint_frontier",
                        lambda *_args, **_kwargs: SimpleNamespace(
                            frontier_truncated=False, exclusions={},
                        ))
    monkeypatch.setattr(joint_planner, "solve_joint",
                        lambda *_args, **_kwargs: PlanningResult(
                            schedule=schedule, selected_course_ids=frozenset({3}),
                            objective=1.0, solver_seconds=0.01,
                        ))
    monkeypatch.setattr(joint_planner, "verify_curriculum_plan",
                        lambda *_args, **_kwargs: {
                            "feasible": False, "quality_passed": False,
                            "hard_violation_count": 1,
                        })
    monkeypatch.setattr(joint_planner, "audit_final_course_admission",
                        lambda *_args, **_kwargs: {"passed": True, "violations": []})
    with pytest.raises(PlanningFailure) as exc:
        joint_planner.build_verified_joint_schedule(version, db, "A")
    assert exc.value.status == "verifier_rejected"
    assert exc.value.details["attempts"]
    assert len(exc.value.details["frontier_hash"]) == 64


def test_scheduler_does_not_call_publication_on_solver_timeout(monkeypatch):
    from app.planner import scheduler
    from app.models.project import ProjectVersion

    db = MagicMock()
    version = SimpleNamespace(
        id=7, project=SimpleNamespace(domain1="IT", domain2="",
                                      constraints_json={}), learning_outcomes=[],
    )
    db.query.return_value.filter.return_value.first.return_value = version
    called = []
    monkeypatch.setattr(scheduler, "build_verified_joint_schedule",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            PlanningFailure("solver_timeout", {"seconds": 30})))
    monkeypatch.setattr(scheduler, "persist_plan_result",
                        lambda **_kwargs: called.append(True))
    with pytest.raises(PlanningFailure) as exc:
        scheduler.build_curriculum_plan(7, db, "A", commit=True)
    assert exc.value.status == "solver_timeout"
    assert called == []


def test_scheduler_passes_a_course_set_as_diversity_reference(monkeypatch):
    from app.planner import scheduler

    db = MagicMock()
    version = SimpleNamespace(
        id=7, project=SimpleNamespace(domain1="IT", domain2="",
                                      constraints_json={}), learning_outcomes=[],
    )
    db.query.return_value.filter.return_value.first.return_value = version
    received = []
    monkeypatch.setattr(scheduler, "build_verified_joint_schedule",
                        lambda *_args, **kwargs: (
                            received.append(kwargs["forbidden_sets"]) or
                            ({1: []}, {"verification": {"feasible": True},
                                       "boundary": {"admission": {"passed": True}},
                                       "planner": {}})
                        ))
    monkeypatch.setattr(scheduler, "calculate_plan_metrics",
                        lambda *_args: {})
    monkeypatch.setattr(scheduler, "build_selection_evidence_snapshot",
                        lambda *_args: {})
    monkeypatch.setattr(scheduler, "persist_plan_result",
                        lambda **_kwargs: {"plan_id": 1})
    scheduler.build_curriculum_plan(7, db, "B", commit=False,
                                    diversity_reference=frozenset({10, 20}))
    assert received == [(frozenset({10, 20}),)]


def test_failed_joint_build_keeps_existing_active_plan_in_database(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.database import Base
    from app.models.plan import Plan
    from app.models.project import Project, ProjectVersion
    from app.planner import scheduler

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            version = ProjectVersion(
                version_number=1,
                project=Project(title="Stable", domain1="IT", domain2="",
                                constraints_json={}),
            )
            db.add(version)
            db.flush()
            old = Plan(project_version_id=version.id, variant_type="A",
                       is_active=1, metrics_json={"stable": True})
            db.add(old)
            db.commit()
            old_id = old.id
            monkeypatch.setattr(scheduler, "build_verified_joint_schedule",
                                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                                    PlanningFailure("verifier_rejected", {"hard": 1})))
            with pytest.raises(PlanningFailure):
                scheduler.build_curriculum_plan(version.id, db, "A", commit=True)
            assert [(plan.id, plan.is_active) for plan in db.query(Plan).all()] == [
                (old_id, 1),
            ]
    finally:
        engine.dispose()


def test_verified_joint_build_persists_exact_schedule(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.database import Base
    from app.models.plan import Plan
    from app.models.project import Project, ProjectVersion
    from app.planner import scheduler

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            version = ProjectVersion(
                version_number=1,
                project=Project(title="Stable", domain1="IT", domain2="",
                                constraints_json={}),
            )
            db.add(version)
            db.commit()
            monkeypatch.setattr(scheduler, "build_verified_joint_schedule",
                                lambda *_args, **_kwargs: (
                                    {1: []},
                                    {"verification": {"feasible": True, "quality_passed": True},
                                     "boundary": {"admission": {"passed": True}},
                                     "planner": {"fingerprint": "known"},
                                     "core_coverage": {"enabled": True, "passed": True,
                                                       "core_coverage": []}},
                                ))
            monkeypatch.setattr(scheduler, "calculate_plan_metrics",
                                lambda *_args: {"metrics_schema_version": 2})
            monkeypatch.setattr(scheduler, "build_selection_evidence_snapshot",
                                lambda *_args: {"version": 1})
            result = scheduler.build_curriculum_plan(version.id, db, "A", commit=True)
            saved = db.get(Plan, result["plan_id"])
            assert result["schedule"] == {1: []}
            assert saved.metrics_json["optimizer"]["selection_method"] == "joint_milp"
            assert saved.metrics_json["joint_planner"]["fingerprint"] == "known"
            assert saved.metrics_json["core_coverage"] == {
                "enabled": True, "passed": True, "core_coverage": [],
            }
    finally:
        engine.dispose()
def test_planning_failure_exposes_structured_audit_context():
    from app.planner.joint_contract import PlanningFailure

    failure = PlanningFailure("infeasible_with_complete_frontier", {"candidate_count": 12})
    assert failure.diagnostic() == {
        "status": "infeasible_with_complete_frontier",
        "details": {"candidate_count": 12},
    }
