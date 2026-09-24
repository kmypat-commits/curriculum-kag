from scripts.prepare_real_cohort_inputs import prepare, resolve_track


def test_resolve_track_rejects_ambiguous_doctorate_credit_total():
    track, reason = resolve_track({
        "education_level": "doctorate", "credits": 180,
        "goal_ru": "Подготовка исследователей в области искусства",
    })
    assert track is None
    assert "not specified" in reason


def test_resolve_track_accepts_explicit_scientific_pedagogical_goal():
    track, _ = resolve_track({
        "education_level": "doctorate", "credits": 180,
        "goal_ru": "Подготовка научно-педагогических кадров",
    })
    assert track == "scientific_pedagogical"


def test_prepare_uses_catalogue_codes_and_versioned_profile():
    payload, reason = prepare({
        "program_id": "1", "split": "test", "education_level": "master",
        "credits": 90, "title_ru": "7M061 Аналитика данных",
        "goal_ru": "Подготовка специалистов по анализу данных",
        "training_direction_code": "7M061", "program_group_code": "M094",
        "training_direction_ru": "Информационные технологии",
        "learning_outcomes": [
            {"code": f"ON{i}", "text": f"Результат обучения {i}"}
            for i in range(1, 4)
        ],
    })
    assert payload is not None, reason
    assert payload["constraints"]["education_area"] == "7M06"
    assert payload["constraints"]["total_semesters"] == 3
    assert payload["constraints"]["master_track"] == "professional"
    assert payload["domain1"] == "Информационные технологии"
