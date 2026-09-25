"""The joint planner must not publish an unverified replacement."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.planner.joint_contract import PlanningFailure


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
                                     "planner": {"fingerprint": "known"}},
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
    finally:
        engine.dispose()
