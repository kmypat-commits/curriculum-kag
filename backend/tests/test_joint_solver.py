"""Feasibility contracts for joint real-course choice and semester placement."""

import pytest


def test_required_low_ranked_course_is_selected_before_utility():
    from dataclasses import replace
    from app.planner.joint_solver import solve_joint
    setup = problem([candidate(1, 10, (1,), {"ON1": .65}, utility=10),
                     candidate(2, 10, (2,), {"ON2": .65}),
                     candidate(3, 10, (1,), {"ON1": .65}, utility=.1)])
    setup = replace(setup, required_course_ids=(3,))
    assert solve_joint(setup, time_limit_seconds=5).selected_course_ids == frozenset({2, 3})


def test_required_course_missing_from_frontier_is_explicit():
    from dataclasses import replace
    from app.planner.joint_solver import solve_joint
    setup = replace(problem([candidate(1, 10, (1,), {"ON1": .65}),
                             candidate(2, 10, (2,), {"ON2": .65})]), required_course_ids=(999,))
    with pytest.raises(PlanningFailure) as exc:
        solve_joint(setup, time_limit_seconds=5)
    assert exc.value.details["reason"] == "required_course_not_admissible"


def test_required_professional_block_selects_confirmed_low_ranked_course():
    from dataclasses import replace
    from app.planner.joint_contract import RequiredCoreBlock
    from app.planner.joint_solver import solve_joint

    setup = problem([candidate(1, 10, (1,), {"ON1": .65}, utility=10),
                     candidate(2, 10, (2,), {"ON2": .65}),
                     candidate(3, 10, (1,), {"ON1": .65}, utility=.1)])
    setup = replace(setup, required_core_blocks=(
        RequiredCoreBlock("wood", (3,), min_courses=1, min_credits=10),
    ))
    assert solve_joint(setup, time_limit_seconds=5).selected_course_ids == frozenset({2, 3})


def test_fixed_course_contributes_to_block_minima_without_double_counting_total():
    from dataclasses import replace
    from app.planner.joint_contract import RequiredCoreBlock
    from app.planner.joint_solver import solve_joint

    setup = problem([
        candidate(1, 10, (1,), {"ON1": .65}, utility=10),
        candidate(2, 10, (2,), {"ON2": .65}),
        candidate(3, 10, (1,), {"ON1": .65}, utility=.1),
        candidate(4, 10, (1,), {"ON1": .65}, utility=9),
    ], target=70, min_load=30, max_load=40)
    setup = replace(setup, required_core_blocks=(
        RequiredCoreBlock("wood", (91, 3), min_courses=2, min_credits=30),
    ))
    result = solve_joint(setup, time_limit_seconds=5)
    assert 3 in result.selected_course_ids
    assert sum(item["credits"] for items in result.schedule.values() for item in items) == 70


@pytest.mark.parametrize("version", [
    "Иностранный язык (профессинальный)",
    "Профессиональный иностранный язык",
    "Иностранный язык (профессиональный) (на английском языке)",
    "Инoстpaнный язык (профессиональный)",
    "Иностранный язык (профессиональный)_профиль",
    "Инoстpaнный язык (профессиональный)_профиль",
])
def test_joint_solver_cannot_select_typographical_versions_of_professional_language(version):
    from app.planner.joint_solver import solve_joint

    first = candidate(1, 10, (1,), {"ON1": 0.65}, utility=3.0)
    second = candidate(2, 10, (2,), {"ON2": 0.65}, utility=3.0)
    alternative = candidate(3, 10, (2,), {"ON2": 0.65}, utility=1.0)
    first.item["title"] = "Иностранный язык (профессиональный)"
    second.item["title"] = version
    alternative.item["title"] = "Методы профильного исследования"
    result = solve_joint(problem([first, second, alternative]), time_limit_seconds=5)
    assert result.selected_course_ids == frozenset({1, 3})


@pytest.mark.parametrize("titles", [
    ("Арабский язык I", "Арабский язык II"),
    ("Английский язык (профессиональный)", "Французский язык (профессиональный)"),
    ("Иностранный язык (профессиональный) 1", "Иностранный язык (профессиональный) 2"),
    ("Методы исследования в психологии", "Методы исследования в социологии"),
])
def test_joint_solver_preserves_distinct_language_levels_and_subjects(titles):
    from app.planner.joint_solver import solve_joint

    first = candidate(1, 10, (1,), {"ON1": 0.65})
    second = candidate(2, 10, (2,), {"ON2": 0.65})
    first.item["title"], second.item["title"] = titles
    result = solve_joint(problem([first, second]), time_limit_seconds=5)
    assert result.selected_course_ids == frozenset({1, 2})

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


def test_infeasible_solver_reports_credit_and_real_lo_upper_bounds():
    from app.planner.joint_solver import solve_joint

    setup = problem([
        candidate(1, 10, (1,), {"ON1": 0.6}),
        candidate(2, 10, (2,), {"ON2": 0.453}),
    ], target=70)
    with pytest.raises(PlanningFailure) as exc:
        solve_joint(setup, time_limit_seconds=5)
    bounds = exc.value.details["necessary_bounds"]
    assert bounds["max_total_credits"] == 60
    assert bounds["target_credits"] == 70
    assert bounds["los_without_real_course"] == ["ON2"]


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


def test_joint_solver_avoids_catalogue_duplicate_of_fixed_regulatory_course():
    from dataclasses import replace
    from app.planner.joint_solver import solve_joint
    duplicate=replace(candidate(1,10,(1,),{'ON1':.65},utility=10.),
                      item={'course_id':1,'title':'  MANAGEMENT psychology  ','credits':10})
    fixed={1:[{'course_id':91,'title':'Management Psychology','credits':20}],
           2:[{'course_id':92,'title':'Research','credits':20}]}
    setup=problem([duplicate,candidate(2,10,(2,),{'ON2':.65}),
                   candidate(3,10,(1,),{'ON1':.65})],fixed=fixed)
    assert solve_joint(setup,time_limit_seconds=5).selected_course_ids == frozenset({2,3})


def test_joint_solver_cannot_select_two_catalogue_ids_with_same_title():
    from dataclasses import replace
    from app.planner.joint_solver import solve_joint
    first=candidate(1,10,(1,),{'ON1':.65})
    second=replace(candidate(2,10,(2,),{'ON2':.65}),
                   item={'course_id':2,'title':'Course 1','credits':10})
    with pytest.raises(PlanningFailure):
        solve_joint(problem([first,second]),time_limit_seconds=5)


def test_joint_solver_preserves_verified_feasible_incumbent_at_time_limit(monkeypatch):
    from app.planner import joint_solver

    setup = problem([
        candidate(1, 10, (1,), {"ON1": 0.65}),
        candidate(2, 10, (2,), {"ON2": 0.65}),
    ])
    real_milp = joint_solver.milp

    def timed_out(**kwargs):
        result = real_milp(**kwargs)
        result.status = 1
        result.message = "Time limit reached"
        return result

    monkeypatch.setattr(joint_solver, "milp", timed_out)
    result = joint_solver.solve_joint(setup, time_limit_seconds=5)
    assert result.selected_course_ids == frozenset({1, 2})
    assert result.optimality_proven is False


@pytest.mark.parametrize("bad_vector", [
    [1., 1., 0., 0.], [1., 1., 0.5, 0.5],
    [1., 1., float("nan"), 1.], [2., 1., 1., 1.],
])
def test_joint_solver_rejects_invalid_time_limit_incumbent(monkeypatch, bad_vector):
    import numpy as np
    from types import SimpleNamespace
    from app.planner import joint_solver

    setup = problem([
        candidate(1, 10, (1,), {"ON1": 0.65}),
        candidate(2, 10, (2,), {"ON2": 0.65}),
    ])
    monkeypatch.setattr(joint_solver, "milp", lambda **kwargs: SimpleNamespace(
        status=1, message="Time limit reached", x=np.array(bad_vector), fun=-2.,
    ))
    with pytest.raises(PlanningFailure):
        joint_solver.solve_joint(setup, time_limit_seconds=5)


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
