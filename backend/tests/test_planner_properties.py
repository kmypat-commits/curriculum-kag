"""Property-style tests for planner invariants without a runtime dependency on Hypothesis."""

import random

from app.planner.invariant_ledger import invariant_errors, run_to_fixed_point, schedule_fingerprint
from app.planner.scheduler_prerequisites import prerequisite_concepts


def test_random_valid_schedules_preserve_structural_invariants():
    rng = random.Random(20260902)
    for _ in range(200):
        semesters = rng.randint(2, 8)
        schedule = {
            semester: [
                {"course_id": semester * 100 + offset, "credits": rng.choice((3, 5, 6))}
                for offset in range(rng.randint(0, 4))
            ]
            for semester in range(1, semesters + 1)
        }
        assert invariant_errors(schedule, semesters) == []


def test_random_invalid_schedules_are_detected():
    rng = random.Random(20260903)
    for _ in range(100):
        schedule = {1: [{"course_id": 1, "credits": 3}, {"course_id": 1, "credits": 3}]}
        if rng.choice((True, False)):
            schedule[0] = [{"course_id": 2, "credits": 3}]
        else:
            schedule[1][0]["credits"] = 0
        assert invariant_errors(schedule, 1)


def test_fixed_point_cycle_is_rejected():
    try:
        run_to_fixed_point(0, lambda value: 1 - value, lambda value: value, max_iterations=8)
    except RuntimeError as error:
        assert "cycle" in str(error).lower()
    else:
        raise AssertionError("A two-state repair cycle must be rejected")


def test_schedule_fingerprint_accepts_mixed_real_and_bridge_items():
    schedule = {
        "1": [
            {"course_id": 42, "bridge_module_id": None, "credits": 5},
            {"course_id": None, "bridge_module_id": 7, "credits": 3},
        ]
    }
    assert len(schedule_fingerprint(schedule)) == 16


def test_schedule_fingerprint_is_independent_of_item_order_inside_a_semester():
    first = {
        1: [
            {"course_id": 42, "credits": 5},
            {"course_id": None, "bridge_module_id": 7, "credits": 3},
        ]
    }
    second = {1: list(reversed(first[1]))}
    assert schedule_fingerprint(first) == schedule_fingerprint(second)


def test_occupational_safety_is_not_an_information_security_prerequisite_concept():
    assert "security" not in prerequisite_concepts("Безопасность жизнедеятельности")
    assert "occupational_safety" in prerequisite_concepts("Безопасность жизнедеятельности")
    assert "security" in prerequisite_concepts("Введение в кибербезопасность")
