import pytest

from scripts.merge_quality_cohort_reports import combine


def report(start: int, count: int) -> dict:
    rows = [
        {
            "case_index": start + index,
            "level": "bachelor",
            "profile": "standard",
            "passed": True,
        }
        for index in range(count)
    ]
    manifest_cases = [
        {"case_index": start + index, "focus": f"frozen input {start + index}"}
        for index in range(count)
    ]
    return {
        "status": "passed", "requested": count, "completed": count,
        "reports": rows, "manifest": {"cases": manifest_cases},
    }


def test_combined_cohorts_preserve_distinct_case_evidence():
    result = combine([report(1, 50), report(51, 30)])
    assert result["status"] == "passed"
    assert result["requested"] == 80
    assert result["passed"] == 80
    assert result["case_indexes"] == list(range(1, 81))


def test_combined_cohorts_reject_overlapping_case_indexes():
    with pytest.raises(ValueError, match="case_index"):
        combine([report(1, 50), report(50, 30)])


def test_combined_cohorts_reject_missing_frozen_identity():
    incomplete = report(1, 1)
    incomplete["manifest"] = {"cases": []}
    with pytest.raises(ValueError, match="frozen input identity"):
        combine([incomplete])
