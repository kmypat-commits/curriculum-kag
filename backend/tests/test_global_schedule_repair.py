from app.planner.global_schedule_repair import repair_schedule_globally


def test_three_way_relocation_balances_feasible_regulatory_schedule():
    # A local move cannot empty term 3 before terms 1/2 refill it, but the
    # complete assignment is feasible: 30, 32, 30, 28 credits.
    schedule = {
        1: [{"title": "Mandatory 1", "credits": 24, "regulatory_required": True}]
        + [{"course_id": i, "title": f"Applied {i}", "credits": c, "latest_semester": 3,
            "prerequisites": []} for i, c in ((1, 6), (2, 5), (3, 5))],
        2: [{"title": "Mandatory 2", "credits": 27, "regulatory_required": True}]
        + [{"course_id": i, "title": f"Applied {i}", "credits": 5, "latest_semester": 3,
            "prerequisites": []} for i in (4, 5)],
        3: [{"title": "Mandatory 3", "credits": 5, "regulatory_required": True}]
        + [{"course_id": i, "title": f"Applied {i}", "credits": 5, "latest_semester": 4,
            "prerequisites": []} for i in range(6, 11)],
        4: [{"title": "Mandatory 4", "credits": 8, "regulatory_required": True},
            {"course_id": 11, "title": "Applied 11", "credits": 5,
             "latest_semester": 4, "prerequisites": []}],
    }
    result = repair_schedule_globally(schedule, num_semesters=4, nominal_load=30)
    assert result is not None
    assert all(27 <= sum(item["credits"] for item in rows) <= 33 for rows in result.values())
    assert [next(s for s, rows in result.items() if any(item["title"] == f"Mandatory {i}" for item in rows))
            for i in range(1, 5)] == [1, 2, 3, 4]
    assert {item["course_id"] for rows in result.values() for item in rows if item.get("course_id")} == set(range(1, 12))
