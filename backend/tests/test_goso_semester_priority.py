from app.planner.semester_rules import minimum_appropriate_semester


def test_regulatory_practice_recommendation_beats_generic_late_stage_name_rule():
    pedagogical = {
        "title": "Педагогическая практика докторанта",
        "type": "goso_bd_practice",
        "regulatory_required": True,
        "recommended_semester": 3,
        "latest_semester": 3,
    }
    assert minimum_appropriate_semester(pedagogical, 6) == 3


def test_non_regulatory_practice_keeps_generic_late_stage_floor():
    ordinary = {"title": "Производственная практика", "type": "pd"}
    assert minimum_appropriate_semester(ordinary, 6) == 4
