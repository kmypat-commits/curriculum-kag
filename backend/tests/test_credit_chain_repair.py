from app.planner.credit_balancing import _rebalance_semester_load


def test_overload_repair_frees_capacity_in_legal_destination_first():
    schedule = {s: [{"title": f"Mandatory {s}", "credits": 27,
                      "regulatory_required": True}] for s in range(1, 9)}
    schedule[1][0]["credits"] = 33
    schedule[2][0]["credits"] = 32
    schedule[4][0]["credits"] = 28
    schedule[2].append({"course_id": 1, "title": "Основы предпринимательства",
                        "credits": 5, "recommended_semester": 1,
                        "latest_semester": 3, "_scoped_epvo_semester": True})
    schedule[3].append({"course_id": 2, "title": "Applied management",
                        "credits": 5, "recommended_semester": 3})
    result = _rebalance_semester_load(schedule, 8, 30)
    assert all(27 <= sum(row["credits"] for row in rows) <= 33 for rows in result.values())
    assert next(s for s, rows in result.items() for row in rows if row.get("course_id") == 1) <= 3


def test_overloaded_term_moves_prerequisite_before_its_child():
    schedule = {
        1: [
            {"title": "Mandatory 1", "credits": 26, "regulatory_required": True},
            {"title": "Foundation", "course_id": 1, "credits": 5, "prerequisites": []},
        ],
        2: [{"title": "Mandatory 2", "credits": 27, "regulatory_required": True}],
        3: [
            {"title": "Mandatory 3", "credits": 23, "regulatory_required": True},
            {"title": "Parent", "course_id": 2, "credits": 5, "prerequisites": [1],
             "recommended_semester": 2, "latest_semester": 3, "_scoped_epvo_semester": True},
        ],
        4: [
            {"title": "Mandatory 4", "credits": 29, "regulatory_required": True},
            {"title": "Child", "course_id": 3, "credits": 5, "prerequisites": [2],
             "recommended_semester": 1, "latest_semester": 4, "_scoped_epvo_semester": True},
        ],
    }
    result = _rebalance_semester_load(schedule, 4, 30)
    assert {semester: sum(row["credits"] for row in rows) for semester, rows in result.items()} == {
        1: 31, 2: 32, 3: 28, 4: 29,
    }
    assert next(semester for semester, rows in result.items() for row in rows if row.get("course_id") == 2) == 2
    assert next(semester for semester, rows in result.items() for row in rows if row.get("course_id") == 3) == 3
