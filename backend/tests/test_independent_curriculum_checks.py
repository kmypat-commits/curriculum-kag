from scripts.independent_curriculum_checks import check_cohort, check_variant


def test_independent_checks_recompute_credits_loads_and_edge_order():
    variant = {
        "credits": 8,
        "semester_loads": {"1": 3, "2": 5},
        "schedule_fingerprint": [[1, "Foundation", 3], [2, "Advanced", 5]],
        "prerequisite_pairs": [{
            "prerequisite_id": 1, "course_id": 2,
            "prerequisite_semester": 1, "course_semester": 2,
        }],
    }
    assert check_variant(variant, target_credits=8, max_load=5) == []
    issues = check_variant(variant, target_credits=7, max_load=4)
    assert {issue["reason"] for issue in issues} == {"target_credits", "semester_overload"}
    issues = check_variant(variant, target_credits=8, max_load=5, min_load=4)
    assert [issue["reason"] for issue in issues] == ["semester_underload"]


def test_independent_checks_reject_reversed_edge_and_duplicate_title():
    variant = {
        "credits": 8,
        "semester_loads": {"1": 3, "2": 5},
        "schedule_fingerprint": [[1, "Foundation", 3], [2, " FOUNDATION ", 5]],
        "prerequisite_pairs": [{
            "prerequisite_id": 1, "course_id": 2,
            "prerequisite_semester": 2, "course_semester": 1,
        }],
    }
    issues = check_variant(variant, target_credits=8, max_load=5)
    assert {issue["reason"] for issue in issues} == {"duplicate_title", "prerequisite_not_before_course"}


def test_cohort_uses_level_target_and_reports_false_internal_pass():
    report = {
        "requested": 2,
        "completed": 2,
        "reports": [
            {"cohort_index": 1, "level": "master", "passed": True, "variants": {
                "A": {"credits": 120, "semester_loads": {"1": 30, "2": 30, "3": 30, "4": 30},
                      "schedule_fingerprint": [[s, f"Course {s}", 30] for s in range(1, 5)]},
            }},
            {"cohort_index": 2, "level": "doctorate", "passed": True, "variants": {
                "B": {"credits": 180, "semester_loads": {str(s): c for s, c in enumerate([30, 30, 30, 30, 20, 40], 1)},
                      "schedule_fingerprint": [[s, f"Course {s}", c] for s, c in enumerate([30, 30, 30, 30, 20, 40], 1)]},
            }},
        ],
    }
    result = check_cohort(report, max_load=33, min_load=27)
    assert result["independently_checked_cases"] == 2
    assert result["cases_with_issues"] == 1
    assert result["issues"][0]["cohort_index"] == 2
    assert {issue["reason"] for issue in result["issues"][0]["checks"]["B"]} == {
        "semester_underload", "semester_overload",
    }
