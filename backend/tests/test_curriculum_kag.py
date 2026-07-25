from types import SimpleNamespace
from unittest.mock import MagicMock

from app.kag.bridge_generator import call_llm, parse_llm_response
from app.planner.scheduler import (
    _rebalance_semester_load,
    _repair_semester_appropriateness,
    schedule_courses,
)
from app.planner.verifier import verify_curriculum_plan


def test_two_semester_credit_tolerance_and_prerequisites():
    courses = [
        {"course_id": 1, "credits": 5, "prerequisites": []},
        {"course_id": 2, "credits": 5, "prerequisites": [1]},
    ] + [{"course_id": i, "credits": 4, "prerequisites": []} for i in range(3, 16)]
    schedule = schedule_courses(courses, 2, 30, MagicMock())
    loads = {semester: sum(item["credits"] for item in items) for semester, items in schedule.items()}
    assert max(loads.values()) <= 33
    semester_by_course = {item["course_id"]: semester for semester, items in schedule.items() for item in items}
    assert semester_by_course[1] < semester_by_course[2]


def test_scheduler_never_places_duplicate_course_titles():
    courses = [
        {"course_id": 1, "title": "Computer Architecture", "credits": 5, "prerequisites": []},
        {"course_id": 2, "title": " computer   architecture ", "credits": 5, "prerequisites": []},
        {"course_id": 3, "title": "Clinical Informatics", "credits": 5, "prerequisites": []},
    ]
    schedule = schedule_courses(courses, 2, 30, MagicMock())
    titles = [item["title"].strip().casefold() for items in schedule.values() for item in items]
    assert titles.count("computer architecture") == 1


def test_scheduler_removes_foundation_aliases_and_component_placeholders():
    courses = [
        {"course_id": 1, "title": "Цифровая криминалистика", "credits": 5, "prerequisites": []},
        {"course_id": 2, "title": "Основы цифровой криминалистики", "credits": 5, "prerequisites": []},
        {"course_id": 3, "title": "обязательный компонент", "credits": 5, "prerequisites": []},
        {"course_id": 4, "title": "Анализ вредоносного ПО", "credits": 5, "prerequisites": []},
    ]
    schedule = schedule_courses(courses, 2, 30, MagicMock())
    titles = [item["title"].strip().casefold() for items in schedule.values() for item in items]
    assert sum("цифровая криминалистика" in title for title in titles) == 1
    assert "обязательный компонент" not in titles


def test_load_repair_can_swap_five_credit_and_three_credit_courses():
    schedule = {
        1: [
            {"course_id": 1, "title": "Foundation", "credits": 5, "prerequisites": []},
            *[
                {"course_id": course_id, "title": f"Course {course_id}", "credits": 3, "prerequisites": []}
                for course_id in range(2, 10)
            ],
        ],
        2: [
            {"course_id": 20, "title": "Applied module", "credits": 5, "prerequisites": []},
            *[
                {"course_id": course_id, "title": f"Course {course_id}", "credits": 3, "prerequisites": []}
                for course_id in range(21, 28)
            ],
        ],
    }
    # 29/26 cannot be repaired by moving a whole 3-credit course because the
    # donor would become underloaded. Exchanging 5 and 3 yields 27/28.
    result = _rebalance_semester_load(schedule, 2, 30)
    loads = {semester: sum(item["credits"] for item in items) for semester, items in result.items()}
    assert loads == {1: 27, 2: 28}


def test_verifier_accepts_plus_five_total_and_plus_three_load():
    schedule = {1: [{"course_id": 1, "credits": 29, "prerequisites": []}], 2: [{"course_id": 2, "credits": 32, "prerequisites": []}]}
    project = SimpleNamespace(constraints_json={"total_semesters": 2, "total_credits": 60, "max_credits_per_semester": 30})
    version = SimpleNamespace(id=1, project=project, learning_outcomes=[])
    db = MagicMock()
    result = verify_curriculum_plan(schedule, version, db)
    assert result["feasible"] is True
    assert result["total_credits"] == 61
    assert result["semester_load_violations"] == []


def test_offline_bridge_is_domain_aware():
    raw = call_llm("prompt", {"domain1": "Public Administration", "domain2": "Information Systems", "gap_los": [{"lo_code": "LO5"}]})
    result = parse_llm_response(raw)
    assert "Public Administration" in result["title"]
    assert "Information Systems" in result["title"]
    assert "LO5" in result["lo_mapping"]


def test_semester_repair_resolves_conflicting_source_recommendation():
    introduction = SimpleNamespace(
        id=1, title="Введение в машинное обучение", domain="IT",
        cycle_component="university", recommended_semester=8,
    )
    advanced = SimpleNamespace(
        id=2, title="Потоковая обработка Kafka", domain="IT",
        cycle_component="university", recommended_semester=8,
    )
    schedule = {semester: [] for semester in range(1, 9)}
    schedule[2] = [{"course_id": 2, "title": advanced.title, "credits": 3, "prerequisites": []}]
    schedule[8] = [{"course_id": 1, "title": introduction.title, "credits": 6, "prerequisites": []}]
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [introduction, advanced]

    repaired = _repair_semester_appropriateness(schedule, 8, 6, db)
    semester_by_course = {
        item["course_id"]: semester
        for semester, items in repaired.items()
        for item in items
    }
    assert semester_by_course[1] <= 3
    assert semester_by_course[2] >= 7
