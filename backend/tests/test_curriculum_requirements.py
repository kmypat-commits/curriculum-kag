import pytest
from pydantic import ValidationError


def test_optional_contract_defaults_off_and_rejects_forged_confirmation():
    from app.schemas.curriculum_requirements import CurriculumRequirements
    assert not CurriculumRequirements().enabled
    with pytest.raises(ValidationError):
        CurriculumRequirements(core_blocks=[{
            "id": "history", "title": "Источниковедение",
            "confirmation": {"author_user_id": 99},
        }])


def test_required_course_ids_are_unique_positive_and_bounded():
    from app.schemas.curriculum_requirements import CurriculumRequirements
    for ids in ([1, 1], [0], list(range(1, 32))):
        with pytest.raises(ValidationError):
            CurriculumRequirements(required_course_ids=ids)


def test_disabled_requirements_are_not_effective():
    from app.planner.core_requirements import effective_requirements
    assert effective_requirements({"enabled": False, "required_course_ids": [1]}) is None


def test_coverage_does_not_count_same_course_twice_or_invent_matches():
    from app.planner.core_requirements import evaluate_coverage
    requirements = {"enabled": True, "required_course_ids": [3], "core_blocks": [
        {"id": "core", "title": "Профиль", "accepted_course_ids": [1],
         "min_courses": 1, "min_credits": 5, "requirement": "required"},
        {"id": "other", "title": "Другой профиль", "accepted_course_ids": [2]},
    ]}
    result = evaluate_coverage(requirements, {1: [{"course_id": 1, "credits": 5}]})
    assert result["unique_core_credits"] == 5
    assert result["core_coverage"][0]["status"] == "covered"
    assert result["core_coverage"][1]["status"] == "gap"
    assert result["required_courses"]["missing"] == [3]
    assert not result["passed"]
