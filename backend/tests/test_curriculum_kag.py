from types import SimpleNamespace
from unittest.mock import MagicMock

from check_text_encoding import looks_like_mojibake
from app.kag.bridge_generator import call_llm, parse_llm_response
from app.planner.scheduler import (
    _complexity_min_semester,
    _credible_professional_lo_by_course,
    _foundation_equivalent_title_key,
    _foundation_max_semester,
    _force_bridge_item,
    _has_foreign_professional_title,
    _infer_schedule_prerequisites,
    _is_it_medicine_support_course,
    _item_minimum_appropriate_semester,
    _minimum_appropriate_semester,
    _rebalance_semester_load,
    _repair_semester_appropriateness,
    _select_exact_professional_subset,
    _shift_excess_load_to_balance_modules,
    _trim_schedule_to_target_credits,
    _unique_items_by_title,
    ensure_credit_bridge_modules,
    schedule_courses,
)
from app.planner.verifier import (
    _ict_competency_audit,
    _semantic_max_semester,
    _semantic_min_semester,
    verify_curriculum_plan,
)
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


def test_foundation_source_semester_is_advisory_except_for_clinical_depth():
    ai = {
        "title": "Основы искусственного интеллекта",
        "recommended_semester": 6,
        "prerequisites": [1],
    }
    surgery = {
        "title": "Основы хирургии",
        "recommended_semester": 8,
        "prerequisites": [1],
    }
    assert _item_minimum_appropriate_semester(ai, 8) == 1
    assert _item_minimum_appropriate_semester(surgery, 8) >= 5
    assert _foundation_max_semester(surgery["title"], 8) == 8
    assert _semantic_min_semester("Основы общей врачебной практики", 8) >= 5
    assert _semantic_max_semester("Основы общей врачебной практики", 8) == 8


def test_inferred_prerequisite_can_raise_final_admission_semester():
    course = SimpleNamespace(
        title="Искусственный интеллект для информационной безопасности",
        domain="it",
        cycle_component="elective",
        recommended_semester=8,
    )
    item = {
        "title": course.title,
        "recommended_semester": 8,
        "prerequisites": [],
    }
    assert _minimum_appropriate_semester(item, course, 8) < 7
    item["prerequisites"] = [42]
    assert _minimum_appropriate_semester(item, course, 8) == 7


def test_it_medicine_rejects_physician_training_without_digital_content():
    domains = [
        "информационно-коммуникационные технологии",
        "здравоохранение",
    ]
    clinical = SimpleNamespace(
        title="Интегрированный курс клинической диагностики",
        credits=10,
        description=(
            "Интерпретировать данные обследования пациента, составлять план "
            "диагностики и лечения, применять доказательную медицину и "
            "сохранять медицинскую информацию."
        ),
    )
    digital = SimpleNamespace(
        title="Цифровые методы клинической диагностики",
        credits=10,
        description="Анализ медицинских данных и алгоритмы поддержки решений.",
    )
    compact_context = SimpleNamespace(
        title="Основы клинических процессов",
        credits=5,
        description="Клиническая диагностика как предметный контекст.",
    )
    assert not _is_it_medicine_support_course(clinical, domains)
    assert _is_it_medicine_support_course(digital, domains)
    assert _is_it_medicine_support_course(compact_context, domains)


def test_foreign_professional_context_is_not_hidden_by_ai_or_digital_words():
    domains = [
        "информационно-коммуникационные технологии",
        "здравоохранение",
    ]
    assert _has_foreign_professional_title(
        SimpleNamespace(title="Искусственный интеллект в маркетинге"),
        domains,
    )
    assert _has_foreign_professional_title(
        SimpleNamespace(title="Цифровая экономика"),
        domains,
    )
    assert _has_foreign_professional_title(
        SimpleNamespace(title="Информационные технологии в экономике"),
        domains,
    )
    assert _has_foreign_professional_title(
        SimpleNamespace(title="Технологии ИИ в управлении предприятием"),
        domains,
    )
    assert _has_foreign_professional_title(
        SimpleNamespace(title="Эмоциональный интеллект"),
        domains,
    )
    assert not _has_foreign_professional_title(
        SimpleNamespace(title="Управление IT-проектами"),
        domains,
    )
    assert not _has_foreign_professional_title(
        SimpleNamespace(title="Базы данных и Business Intelligence"),
        domains,
    )


def test_load_shift_never_splits_real_epvo_course_credits():
    heavy = {
        "course_id": 809,
        "title": "Интегрированный курс клинической диагностики",
        "credits": 9,
        "prerequisites": [],
    }
    schedule = {
        1: [{"course_id": index, "credits": 3, "prerequisites": []} for index in range(1, 10)],
        2: [
            *[{"course_id": index, "credits": 5, "prerequisites": []} for index in range(20, 26)],
            heavy,
        ],
    }
    version = SimpleNamespace(
        project=SimpleNamespace(
            constraints_json={"program_type": "interdisciplinary"},
        ),
        learning_outcomes=[],
    )
    result = _shift_excess_load_to_balance_modules(
        schedule, version, nominal_load=30, db=MagicMock()
    )
    assert heavy["credits"] == 9
    assert not any(
        item.get("bridge_module_id") is not None
        for items in result.values()
        for item in items
    )


def test_total_credit_trim_never_changes_real_course_credits():
    real = {
        "course_id": 42,
        "title": "Системы баз данных",
        "credits": 5,
        "prerequisites": [],
    }
    schedule = {
        1: [real],
        2: [{"course_id": 43, "title": "Алгоритмы", "credits": 5, "prerequisites": []}],
    }
    _trim_schedule_to_target_credits(schedule, target_credits=8, db=MagicMock())
    assert real["credits"] == 5


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


def test_plan_local_prerequisites_use_only_earlier_semesters():
    schedule = {
        1: [{"course_id": 1, "title": "Алгоритмы и структуры данных", "credits": 5}],
        2: [{"course_id": 2, "title": "Прикладное машинное обучение", "credits": 5}],
        3: [{"course_id": 3, "title": "Информационная безопасность", "credits": 5}],
        4: [{"course_id": 4, "title": "Компьютерные сети", "credits": 5}],
    }
    stats = _infer_schedule_prerequisites(schedule)
    assert schedule[2][0]["prerequisites"] == [1]
    assert schedule[3][0]["prerequisites"] == []
    assert stats["edge_count"] == 1


def test_regulatory_research_is_not_inferred_as_coursework_prerequisite():
    schedule = {
        1: [
            {
                "course_id": 1,
                "title": "Научно-исследовательская работа магистранта 1",
                "credits": 6,
                "regulatory_required": True,
            },
            {"course_id": 2, "title": "Методология научных исследований", "credits": 5},
        ],
        2: [
            {
                "course_id": 3,
                "title": "Современные методы исследований и анализа данных",
                "credits": 5,
            }
        ],
    }
    _infer_schedule_prerequisites(schedule)
    assert schedule[2][0]["prerequisites"] == [2]


def test_ict_competency_audit_detects_missing_security_block():
    courses = [
        SimpleNamespace(title="Алгоритмы и структуры данных"),
        SimpleNamespace(title="Базы данных"),
        SimpleNamespace(title="Операционные системы и компьютерные сети"),
        SimpleNamespace(title="Системы искусственного интеллекта"),
        SimpleNamespace(title="Основы научных исследований и проект"),
    ]
    audit = _ict_competency_audit(
        courses,
        {"education_level": "bachelor", "direction_code": "6B061", "group_code": "B057"},
    )
    assert audit["applicable"] is True
    assert audit["passed"] is False
    assert audit["missing"] == ["information_security"]


def test_final_admission_evidence_excludes_weak_and_goso_only_matches():
    version = SimpleNamespace(
        id=7,
        learning_outcomes=[
            SimpleNamespace(id=1, lo_code="LO1"),
            SimpleNamespace(id=2, lo_code="LO-GOSO-B1"),
        ],
    )
    matches = [
        SimpleNamespace(course_id=10, lo_id=1, score=0.61, evidence_json={}),
        SimpleNamespace(course_id=11, lo_id=1, score=0.39, evidence_json={}),
        SimpleNamespace(course_id=12, lo_id=2, score=0.95, evidence_json={}),
    ]
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = matches
    evidence = _credible_professional_lo_by_course(version, {10, 11, 12}, db)
    assert evidence == {10: {"LO1"}}


def test_meaningful_bridge_fills_credit_gap_before_replacing_real_course():
    module = SimpleNamespace(
        id=9,
        course_id="CORE_BRIDGE_1",
        title="Интеграционный модуль: IT и медицина",
        credits=5,
        recommended_semester=4,
        prerequisites=[],
    )
    items = [{"course_id": 1, "title": "Базы данных", "credits": 5, "prerequisites": []}]
    result = _force_bridge_item(items, module, target_credits=10)
    assert len(result) == 2
    assert sum(item["credits"] for item in result) == 10
    assert result[-1]["bridge_module_id"] == 9


def test_meaningful_bridge_never_replaces_regulatory_course():
    module = SimpleNamespace(
        id=9,
        course_id="CORE_BRIDGE_1",
        title="Интеграционный модуль",
        credits=5,
        recommended_semester=4,
        prerequisites=[],
    )
    items = [
        {
            "course_id": 1,
            "title": "Обязательная дисциплина ГОСО",
            "credits": 5,
            "regulatory_required": True,
            "prerequisites": [],
        },
        {"course_id": 2, "title": "Профильная дисциплина", "credits": 5, "prerequisites": []},
    ]
    result = _force_bridge_item(items, module, variant_type="C", target_credits=10)
    assert any(item.get("course_id") == 1 for item in result)
    assert not any(item.get("course_id") == 2 for item in result)


def test_credit_gap_bridge_never_claims_goso_outcomes():
    version = SimpleNamespace(
        id=7,
        project=SimpleNamespace(
            domain1="IT",
            domain2=None,
            constraints_json={"total_semesters": 8},
        ),
        learning_outcomes=[
            SimpleNamespace(lo_code="LO1", lo_text="Разрабатывать информационные системы"),
            SimpleNamespace(lo_code="LO-GOSO-B1", lo_text="Обязательный результат ГОСО"),
        ],
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    modules = ensure_credit_bridge_modules(version, db, needed_credits=5, slots=1)
    assert len(modules) == 1
    assert modules[0].target_los == ["LO1"]


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


def test_scheduler_reserves_late_window_for_advanced_clinical_course():
    courses = [
        {
            "course_id": 1,
            "title": "Внутренние болезни",
            "credits": 10,
            "recommended_semester": 8,
            "prerequisites": [],
        },
        *[
            {
                "course_id": index,
                "title": f"Базовая дисциплина {index}",
                "credits": 5,
                "recommended_semester": 1,
                "prerequisites": [],
            }
            for index in range(2, 10)
        ],
    ]
    schedule = schedule_courses(courses, 8, 30, MagicMock())
    semester = next(
        value for value, items in schedule.items()
        if any(item.get("course_id") == 1 for item in items)
    )
    assert semester >= 7


def test_load_rebalance_does_not_pull_late_course_into_early_semester():
    late = {
        "course_id": 1,
        "title": "Внутренние болезни",
        "credits": 10,
        "recommended_semester": 8,
        "prerequisites": [],
    }
    schedule = {
        1: [{"course_id": 2, "title": "Foundation", "credits": 20, "prerequisites": []}],
        7: [late, {"course_id": 3, "title": "Late support", "credits": 25, "prerequisites": []}],
        8: [{"course_id": 4, "title": "Capstone", "credits": 30, "prerequisites": []}],
    }
    repaired = _rebalance_semester_load(schedule, 8, 30)
    semester = next(
        value for value, items in repaired.items()
        if any(item.get("course_id") == 1 for item in items)
    )
    assert semester >= 7


def test_load_rebalance_can_exchange_mid_program_bridge_by_one_credit():
    bridge = {
        "bridge_module_id": 9,
        "title": "Интеграционный модуль: IT и медицина",
        "credits": 3,
        "recommended_semester": 4,
        "latest_semester": 6,
        "prerequisites": [],
    }
    schedule = {
        4: [bridge, {"course_id": 1, "title": "Core", "credits": 23, "prerequisites": []}],
        5: [{"course_id": 2, "title": "Stable load", "credits": 30, "prerequisites": []}],
        6: [
            {
                "course_id": 3,
                "title": "Искусственный интеллект: принципы и применение",
                "credits": 4,
                "recommended_semester": 3,
                "prerequisites": [],
            },
            {"course_id": 4, "title": "Applied block", "credits": 28, "prerequisites": []},
        ],
    }
    repaired = _rebalance_semester_load(schedule, 8, 30)
    loads = {
        semester: sum(int(item["credits"]) for item in items)
        for semester, items in repaired.items()
    }
    assert loads[4] >= 27
    assert loads[6] <= 33


def test_scheduler_removes_foundation_aliases_and_component_placeholders():
    courses = [
        {"course_id": 1, "title": "Цифровая криминалистика", "credits": 5, "prerequisites": []},
        {"course_id": 2, "title": "Основы цифровой криминалистики", "credits": 5, "prerequisites": []},
        {"course_id": 5, "title": "Основы программирования Python", "credits": 3, "prerequisites": []},
        {"course_id": 6, "title": "Основы программирования", "credits": 6, "prerequisites": []},
        {"course_id": 3, "title": "обязательный компонент", "credits": 5, "prerequisites": []},
        {"course_id": 4, "title": "Анализ вредоносного ПО", "credits": 5, "prerequisites": []},
    ]
    schedule = schedule_courses(courses, 2, 30, MagicMock())
    titles = [item["title"].strip().casefold() for items in schedule.values() for item in items]
    assert sum("цифровая криминалистика" in title for title in titles) == 1
    assert sum("основы программирования" in title for title in titles) == 1
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
