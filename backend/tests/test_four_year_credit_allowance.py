import pytest
from backend.scripts.independent_curriculum_checks import check_variant


@pytest.mark.parametrize("total, accepted", [(239, False), (240, True), (243, True), (244, True), (245, False)])
def test_independent_four_year_credit_range(total, accepted):
    rows = [[s, f"Course {s}", 30] for s in range(1, 9)]
    rows[-1][2] += total - 240
    variant = {"schedule_fingerprint": rows, "credits": total,
               "semester_loads": {str(s): c for s, _, c in rows}}
    issues = check_variant(variant, target_credits=240, max_load=40, num_semesters=8)
    assert (not any(row["reason"] == "target_credits" for row in issues)) is accepted


@pytest.mark.parametrize("total, accepted", [(244, True), (245, False)])
def test_verifier_four_year_cap_and_manual_adjustment_warning(total, accepted):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from app.planner.verifier import verify_curriculum_plan
    version = SimpleNamespace(id=1, learning_outcomes=[], project=SimpleNamespace(
        domain1="", domain2="", constraints_json={"total_semesters": 8,
        "total_credits": 240, "max_credits_per_semester": 31, "credit_tolerance": 3}))
    schedule = {s: [{"credits": 30, "title": f"Course {s}"}] for s in range(1, 9)}
    schedule[8][0]["credits"] += total - 240
    result = verify_curriculum_plan(schedule, version, MagicMock())
    assert (not result["credit_violations"]) is accepted
    if accepted:
        assert result.get("credit_adjustment_required") is True
        assert result["maximum_total_credits"] == 244


def test_other_duration_keeps_exact_independent_credit_requirement():
    variant = {"schedule_fingerprint": [[1, "A", 60], [2, "B", 63]],
               "credits": 123, "semester_loads": {"1": 60, "2": 63}}
    assert any(issue["reason"] == "target_credits" for issue in
               check_variant(variant, target_credits=120, max_load=70, num_semesters=2))


def test_generation_acceptance_matches_approved_credit_range():
    from app.planner.credit_policy import total_credits_accepted, total_credit_tolerance
    constraints = {"total_credits": 240, "total_semesters": 8, "credit_tolerance": 3}
    assert [total_credits_accepted(value, constraints) for value in (239, 240, 243, 244, 245)] == [False, True, True, True, False]
    assert total_credit_tolerance(constraints) == 4
    other = {"total_credits": 120, "total_semesters": 4, "credit_tolerance": 3}
    assert not total_credits_accepted(123, other)
    assert total_credit_tolerance(other) == 0
