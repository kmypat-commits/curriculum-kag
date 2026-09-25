"""Feasibility contracts for joint real-course choice and semester placement."""

import pytest

from app.planner.joint_contract import Candidate, PlanningFailure, PlanningProblem


def candidate(course_id, credits, semesters, lo_scores, *, parents=(), utility=1.0,
              shares=(1.0, 0.0)):
    return Candidate(
        course_id=course_id,
        item={"course_id": course_id, "title": f"Course {course_id}",
              "credits": credits, "prerequisites": list(parents)},
        allowed_semesters=semesters, prerequisites=parents,
        lo_scores=lo_scores, domain_shares=shares, utility=utility,
    )


def problem(candidates, *, fixed=None, los=("ON1", "ON2"), target=60,
            min_load=30, max_load=30, domain_minima=(0.0, 0.0)):
    return PlanningProblem(
        candidates=tuple(candidates),
        fixed_schedule=fixed if fixed is not None else {
            1: [{"course_id": 91, "credits": 20, "regulatory_required": True}],
            2: [{"course_id": 92, "credits": 20, "regulatory_required": True}],
        },
        required_los=los, target_credits=target, credit_tolerance=0,
        min_load=min_load, max_load=max_load,
        domain_minima=domain_minima, exclusions={}, frontier_truncated=False,
    )


def test_joint_solver_selects_feasible_alternative_to_overfull_chain():
    from app.planner.joint_solver import solve_joint

    setup = problem([
        candidate(1, 10, (1,), {"ON1": 0.6}, utility=1.0),
        candidate(2, 10, (2,), {"ON2": 0.6}, utility=1.0),
        candidate(3, 10, (2,), {"ON1": 0.9}, parents=(4,), utility=2.0),
        candidate(4, 10, (1,), {"ON1": 0.4}, utility=1.0),
    ])
    result = solve_joint(setup, time_limit_seconds=5)
    assert result.selected_course_ids == frozenset({1, 2})
    assert [sum(item["credits"] for item in result.schedule[s]) for s in (1, 2)] == [30, 30]


def test_joint_solver_fails_honestly_when_required_lo_has_no_real_evidence():
    from app.planner.joint_solver import solve_joint

    setup = problem([
        candidate(1, 10, (1,), {"ON1": 0.6}),
        candidate(2, 10, (2,), {"ON2": 0.453}),
    ])
    with pytest.raises(PlanningFailure) as exc:
        solve_joint(setup, time_limit_seconds=5)
    assert exc.value.status == "infeasible_with_complete_frontier"


def test_joint_solver_respects_exact_domain_quota():
    from app.planner.joint_solver import solve_joint

    setup = problem([
        candidate(1, 10, (1,), {"ON1": 0.6}, shares=(1.0, 0.0)),
        candidate(2, 10, (2,), {"ON2": 0.6}, shares=(0.0, 1.0)),
    ], domain_minima=(10.0, 10.0))
    assert solve_joint(setup, time_limit_seconds=5).selected_course_ids == frozenset({1, 2})
    impossible = problem(setup.candidates, domain_minima=(15.0, 10.0))
    with pytest.raises(PlanningFailure):
        solve_joint(impossible, time_limit_seconds=5)


def test_joint_solver_orders_parent_before_child_and_honours_fixed_parent():
    from app.planner.joint_solver import solve_joint

    setup = problem([
        candidate(1, 10, (1,), {"ON1": 0.6}),
        candidate(2, 10, (2,), {"ON2": 0.6}, parents=(1, 91)),
    ])
    result = solve_joint(setup, time_limit_seconds=5)
    assert result.selected_course_ids == frozenset({1, 2})
    assert any(item.get("course_id") == 1 for item in result.schedule[1])
    assert any(item.get("course_id") == 2 for item in result.schedule[2])

    impossible = problem([
        candidate(1, 10, (2,), {"ON1": 0.6}),
        candidate(2, 10, (1,), {"ON2": 0.6}, parents=(1,)),
    ])
    with pytest.raises(PlanningFailure):
        solve_joint(impossible, time_limit_seconds=5)


def test_joint_solver_forbids_exact_previous_variant_and_is_deterministic():
    from app.planner.joint_solver import solve_joint

    setup = problem([
        candidate(1, 10, (1,), {"ON1": 0.6}),
        candidate(2, 10, (2,), {"ON2": 0.6}),
    ])
    first = solve_joint(setup, time_limit_seconds=5)
    second = solve_joint(setup, time_limit_seconds=5)
    assert first.schedule == second.schedule
    with pytest.raises(PlanningFailure):
        solve_joint(setup, time_limit_seconds=5,
                    forbidden_sets=(first.selected_course_ids,))


def test_joint_solver_reports_timeout_not_infeasibility(monkeypatch):
    from types import SimpleNamespace

    from app.planner import joint_solver

    setup = problem([
        candidate(1, 10, (1,), {"ON1": 0.6}),
        candidate(2, 10, (2,), {"ON2": 0.6}),
    ])
    monkeypatch.setattr(joint_solver, "milp", lambda **_kwargs: SimpleNamespace(
        status=1, message="Time limit reached", x=None,
    ))
    with pytest.raises(PlanningFailure) as exc:
        joint_solver.solve_joint(setup, time_limit_seconds=0.01)
    assert exc.value.status == "solver_timeout"


def test_joint_solver_rejects_invalid_candidate_window():
    from app.planner.joint_solver import solve_joint

    setup = problem([
        candidate(1, 10, (), {"ON1": 0.6}),
        candidate(2, 10, (2,), {"ON2": 0.6}),
    ])
    with pytest.raises(PlanningFailure) as exc:
        solve_joint(setup, time_limit_seconds=5)
    assert exc.value.status == "invalid_candidate_data"


def test_joint_solver_cannot_fill_credit_gap_with_unverified_real_course():
    from app.planner.joint_solver import solve_joint

    setup = problem([
        candidate(1, 5, (1,), {"ON1": 0.6}),
        candidate(2, 10, (2,), {"ON2": 0.6}),
        candidate(3, 5, (1,), {"ON1": 0.1}),
    ], min_load=20, max_load=35)
    with pytest.raises(PlanningFailure) as exc:
        solve_joint(setup, time_limit_seconds=5)
    assert exc.value.status in {"invalid_candidate_data", "infeasible_with_complete_frontier"}


def test_joint_solver_reports_bounded_frontier_without_claiming_global_infeasibility():
    from dataclasses import replace

    from app.planner.joint_solver import solve_joint

    setup = replace(problem([
        candidate(1, 10, (1,), {"ON1": 0.6}),
        candidate(2, 10, (2,), {"ON2": 0.453}),
    ]), frontier_truncated=True)
    with pytest.raises(PlanningFailure) as exc:
        solve_joint(setup, time_limit_seconds=5)
    assert exc.value.status == "no_solution_in_bounded_frontier"


def test_joint_solver_enforces_verifier_combined_lo_coverage_not_just_real_threshold():
    from app.planner.joint_solver import solve_joint

    setup = problem([
        candidate(1, 10, (1,), {"ON1": 0.55}, utility=2.0),
        candidate(2, 10, (1,), {"ON1": 0.65}, utility=1.0),
        candidate(3, 10, (2,), {"ON2": 0.65}, utility=1.0),
    ])
    result = solve_joint(setup, time_limit_seconds=5)
    assert result.selected_course_ids == frozenset({2, 3})


def test_joint_solver_retries_another_placement_of_same_valid_course_set():
    from app.planner.joint_solver import solve_joint

    setup = problem([
        candidate(1, 10, (1, 2), {"ON1": 0.65}),
        candidate(2, 10, (1, 2), {"ON2": 0.65}),
    ])
    first = solve_joint(setup, time_limit_seconds=5)
    first_placement = frozenset(
        (item["course_id"], semester)
        for semester, items in first.schedule.items()
        for item in items if item.get("course_id") in {1, 2}
    )
    second = solve_joint(setup, time_limit_seconds=5,
                         forbidden_placements=(first_placement,))
    second_placement = frozenset(
        (item["course_id"], semester)
        for semester, items in second.schedule.items()
        for item in items if item.get("course_id") in {1, 2}
    )
    assert second.selected_course_ids == first.selected_course_ids
    assert second_placement != first_placement
