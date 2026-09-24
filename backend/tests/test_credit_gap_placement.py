from app.planner.schedule_credit_gap import eligible_real_course_semesters
from app.planner.course_scheduling import schedule_courses
from unittest.mock import MagicMock


def schedule():
    return {term: [{"course_id": 100 + term, "credits": 30 if term < 4 else 20}]
            for term in range(1, 9)}


def test_intro_course_cannot_fill_a_late_credit_gap():
    candidate = {"course_id": 1, "title": "Введение в исследования", "credits": 5,
                 "recommended_semester": 2}
    assert eligible_real_course_semesters(schedule(), candidate, 33) == []
    assert candidate["recommended_semester"] == 2


def test_intro_uses_early_available_capacity():
    rows = schedule()
    rows[2][0]["credits"] = 25
    assert eligible_real_course_semesters(rows, {"course_id": 1, "title": "Введение в исследования", "credits": 5}, 33) == [2]


def test_missing_prerequisite_cannot_be_ignored():
    assert eligible_real_course_semesters(schedule(), {"course_id": 1, "title": "Course", "credits": 5, "prerequisites": [999]}, 33) == []


def test_parent_and_child_bound_restored_course():
    rows = schedule()
    rows[7][0]["prerequisites"] = [1]
    candidate = {"course_id": 1, "title": "Course", "credits": 5, "prerequisites": [104]}
    assert eligible_real_course_semesters(rows, candidate, 33) == [5, 6]


def test_initial_load_balancer_keeps_intro_inside_its_window():
    courses = [{"course_id": 100 + term, "title": f"Fixed block {term}",
                "credits": 28 if term == 1 else 22 if term == 8 else 30,
                "recommended_semester": term, "regulatory_required": True,
                "type": "goso_fixed", "prerequisites": []} for term in range(1, 9)]
    courses.append({"course_id": 1, "title": "Введение в специальность", "credits": 5,
                    "recommended_semester": 1, "prerequisites": []})
    result = schedule_courses(courses, 8, 30, MagicMock())
    term = next(term for term, rows in result.items() if any(row.get("course_id") == 1 for row in rows))
    assert term <= 3
