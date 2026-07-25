from types import SimpleNamespace

from app.planner.goso import _definitions_for_constraints, ensure_goso_items


def _sum(definitions, component):
    return sum(item[2] for item in definitions if item[4] == component)


def test_goso_completion_volumes_by_level_and_track():
    bachelor = _definitions_for_constraints({"education_level": "bachelor", "total_semesters": 8, "total_credits": 240})
    master = _definitions_for_constraints({"education_level": "master", "master_track": "scientific_pedagogical", "total_semesters": 4, "total_credits": 120})
    profile = _definitions_for_constraints({"education_level": "master", "master_track": "professional", "total_semesters": 2, "total_credits": 60})
    doctorate = _definitions_for_constraints({"education_level": "doctorate", "total_semesters": 6, "total_credits": 180})

    assert _sum(bachelor, "goso_final") == 8
    assert _sum(master, "goso_research") == 24
    assert _sum(master, "goso_final") == 8
    assert _sum(profile, "goso_research") == 13
    assert _sum(profile, "goso_final") == 8
    assert _sum(doctorate, "goso_research") == 123
    assert _sum(doctorate, "goso_final") == 12
    doctoral_research = [item for item in doctorate if item[4] == "goso_research"]
    assert [item[2] for item in doctoral_research] == [20, 20, 20, 20, 22, 21]
    assert [item[3] for item in doctoral_research] == [1, 2, 3, 4, 5, 6]


def test_international_program_does_not_receive_goso_courses():
    version = SimpleNamespace(project=SimpleNamespace(constraints_json={"jurisdiction": "INTERNATIONAL"}))
    assert ensure_goso_items(version, None) == []
