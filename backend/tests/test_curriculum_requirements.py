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


def _valid_constraints():
    return {
        "education_level": "bachelor", "education_area": "6B06",
        "direction_code": "6B061", "group_code": "B057",
        "program_type": "standard", "instruction_language": "ru",
        "duration_years": 4, "total_semesters": 8,
        "total_credits": 240, "max_credits_per_semester": 30,
    }


@pytest.mark.parametrize("requirements", [
    {"enabled": True, "required_course_ids": [0]},
    {"enabled": True, "core_blocks": [{
        "id": "core", "title": "Профиль",
        "confirmation": {"author_user_id": 99, "status": "approved"},
    }]},
])
def test_constraints_update_rejects_invalid_or_forged_requirements(requirements):
    from app.api.projects import ProjectConstraintsUpdate

    constraints = _valid_constraints()
    constraints["curriculum_requirements"] = requirements
    with pytest.raises(ValidationError):
        ProjectConstraintsUpdate(constraints=constraints)


def test_project_creation_rejects_forged_requirements():
    from app.api.projects import ProjectCreate

    constraints = _valid_constraints()
    constraints["curriculum_requirements"] = {
        "enabled": True,
        "core_blocks": [{"id": "core", "title": "Профиль",
                         "confirmation": {"author_user_id": 99}}],
    }
    with pytest.raises(ValidationError):
        ProjectCreate(title="Programme", goal="Train specialists", domain1="ICT",
                      domain2="", learning_outcomes=[{"lo_code": "LO1", "lo_text": "Apply"}],
                      constraints=constraints)


def test_enabled_requirements_reject_unknown_internal_course_ids():
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.api.projects import _validate_requirement_course_existence
    from app.models.course import Course

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Course.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(Course.__table__.insert(), {
            "id": 11, "course_id": "EPVO-11", "title": "Real course",
            "domain": "ICT", "credits": 5,
        })
    with Session(engine) as db:
        constraints = {"curriculum_requirements": {
            "enabled": True,
            "required_course_ids": [11, 12],
            "core_blocks": [{"id": "web", "title": "Web",
                             "accepted_course_ids": [11, 13]}],
        }}
        with pytest.raises(HTTPException) as exc:
            _validate_requirement_course_existence(constraints, db)
        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "required_course_missing"
        assert exc.value.detail["course_ids"] == [12, 13]

        constraints["curriculum_requirements"]["enabled"] = False
        _validate_requirement_course_existence(constraints, db)
