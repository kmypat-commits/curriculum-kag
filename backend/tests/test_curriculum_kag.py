from types import SimpleNamespace
from unittest.mock import MagicMock

from check_text_encoding import looks_like_mojibake
from app.kag.bridge_generator import call_llm, parse_llm_response
from app.planner.scheduler import (
    _complexity_min_semester,
    _foundation_equivalent_title_key,
    _rebalance_semester_load,
    _repair_semester_appropriateness,
    _select_exact_professional_subset,
    _unique_items_by_title,
    schedule_courses,
)
from app.planner.verifier import _semantic_min_semester, verify_curriculum_plan
from app.services.content_localization import register_course_translations


def test_encoding_gate_distinguishes_clean_russian_and_kazakh_from_mojibake():
    assert looks_like_mojibake("РџР»Р°РЅ СѓС‡РµР±РЅРѕР№ РїСЂРѕРіСЂР°РјРјС‹")
    assert looks_like_mojibake("ÐÐ»Ð°Ð½ ÑÑÐµÐ±Ð½Ð¾Ð¹ Ð¿ÑÐ¾Ð³ÑÐ°Ð¼Ð¼Ñ")
    assert not looks_like_mojibake("План образовательной программы")
    assert not looks_like_mojibake("Білім беру бағдарламасының жоспары")


def test_research_methods_are_early_but_not_locked_to_semester_three_postgraduate():
    item = {"title": "Методы научных исследований", "type": "elective"}
    assert _complexity_min_semester(item, 6) == 1
    assert _semantic_min_semester(item["title"], 6) == 1
    assert _complexity_min_semester(item, 8) >= 2
    assert _semantic_min_semester(item["title"], 8) >= 2


def test_research_methodology_title_variants_share_semantic_key():
    variants = {
        "методология исследования",
        "методология исследований",
        "методология научного исследования",
        "методология научных исследований",
    }
    assert {
        _foundation_equivalent_title_key(title)
        for title in variants
    } == {"semantic research methodology"}


def test_common_catalogue_aliases_are_semantically_deduplicated():
    items = [
        {"course_id": 1, "title": "Базы данных", "credits": 5},
        {"course_id": 2, "title": "Системы баз данных", "credits": 4},
        {"course_id": 3, "title": "Алгоритмы и структуры данных", "credits": 3},
        {"course_id": 4, "title": "Алгоритмы, структуры данных и программирование", "credits": 5},
        {"course_id": 5, "title": "Управление IT-проектами", "credits": 5},
        {"course_id": 6, "title": "Проектный менеджмент", "credits": 2},
    ]
    titles = [item["title"] for item in _unique_items_by_title(items)]
    assert titles == [
        "Базы данных",
        "Алгоритмы и структуры данных",
        "Управление IT-проектами",
    ]


def test_verified_translations_are_stored_in_database_without_json_write():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    stored = register_course_translations({
        42: {
            "title": {"ru": "Анализ данных", "kk": "Деректерді талдау", "en": "Data Analysis"},
            "description": {"ru": "Описание", "kk": "Сипаттама", "en": "Description"},
            "review_status": "verified_epvo",
            "source": "epvo_normalized_repository",
        }
    }, db)
    assert stored == 3
    assert db.add.call_count == 3
    assert db.flush.call_count == 1


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


def test_exact_goso_remainder_preserves_both_domain_quotas():
    candidates = [
        {"course_id": 1, "credits": 5},
        {"course_id": 2, "credits": 5},
        {"course_id": 3, "credits": 5},
        {"course_id": 4, "credits": 5},
        {"course_id": 5, "credits": 5},
        {"course_id": 6, "credits": 5},
    ]
    # Domain 1 has the individually strongest courses. A coverage-only
    # knapsack would select five of them and fail the interdisciplinary quota.
    evidence = {
        1: (0b0001, 0.99),
        2: (0b0010, 0.98),
        3: (0b0100, 0.97),
        4: (0b1000, 0.96),
        5: (0b0011, 0.80),
        6: (0b1100, 0.79),
    }
    domain_index = {1: 0, 2: 0, 3: 0, 4: 0, 5: 1, 6: 1}
    selected = _select_exact_professional_subset(
        candidates,
        evidence,
        capacity=25,
        domain_index_by_course=domain_index,
        minimum_domain_credits=(7, 7),
    )
    selected_ids = {candidates[index]["course_id"] for index in selected}
    assert sum(candidates[index]["credits"] for index in selected) == 25
    assert sum(candidates[index]["credits"] for index in selected if domain_index[candidates[index]["course_id"]] == 0) >= 7
    assert sum(candidates[index]["credits"] for index in selected if domain_index[candidates[index]["course_id"]] == 1) >= 7
    assert selected_ids & {5, 6} == {5, 6}


def test_exact_goso_remainder_keeps_near_optimal_variants_distinct():
    candidates = [
        {"course_id": course_id, "credits": 5}
        for course_id in range(1, 7)
    ]
    evidence = {
        course_id: (0b1111, 1.0 - course_id * 0.005)
        for course_id in range(1, 7)
    }
    domains = {course_id: course_id % 2 for course_id in range(1, 7)}
    selected_a = _select_exact_professional_subset(
        candidates, evidence, 25, domains, (5, 5), "A"
    )
    selected_b = _select_exact_professional_subset(
        candidates, evidence, 25, domains, (5, 5), "B"
    )
    selected_c = _select_exact_professional_subset(
        candidates, evidence, 25, domains, (5, 5), "C"
    )
    assert selected_a != selected_b
    assert selected_a != selected_c
    assert sum(candidates[index]["credits"] for index in selected_b) == 25
