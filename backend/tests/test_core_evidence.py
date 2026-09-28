from types import SimpleNamespace

import pytest


def _course(description="Проектирование и обработка изделий из древесины."):
    return SimpleNamespace(
        id=17, course_id="EPVO-17", title="Технология деревообработки",
        domain="Производство", credits=5, language="ru",
        description=description, topics=["Обработка древесины"],
        learning_outcomes=["Проектировать изделия из древесины"],
        assessment_methods=["Проект"],
    )


def _block(description="Технологии обработки древесины"):
    return {"id": "wood", "title": "Деревообработка", "description": description,
            "lo_codes": ["LO1"], "requirement": "required", "min_courses": 1,
            "min_credits": 5, "accepted_course_ids": [17]}


def test_confirmation_requires_a_real_non_title_excerpt_and_server_actor():
    from app.planner.core_evidence import create_confirmation

    with pytest.raises(ValueError, match="source_excerpt_missing"):
        create_confirmation(_block(), _course(), source_field="description",
                            excerpt="Обработка металлов", actor_user_id=7,
                            project_version_id=3, rationale="Изучено содержание")
    record = create_confirmation(
        _block(), _course(), source_field="description",
        excerpt="обработка изделий из древесины", actor_user_id=7,
        project_version_id=3, rationale="Изучено содержание",
    )
    assert record["status"] == "confirmed"
    assert record["author_user_id"] == 7
    assert record["project_version_id"] == 3
    assert record["source_reference"] == "EPVO-17"
    assert record["source_field"] == "description"
    assert record["source_excerpt"] == "обработка изделий из древесины"
    assert len(record["content_hash"]) == 64


def test_confirmation_is_invalidated_by_course_or_block_content_change():
    from app.planner.core_evidence import create_confirmation, verified_matches

    block = _block()
    course = _course()
    record = create_confirmation(
        block, course, source_field="description", excerpt="изделий из древесины",
        actor_user_id=7, project_version_id=3, rationale="Изучено содержание",
    )
    assert verified_matches([block], [record], {17: course}, project_version_id=3) == {"wood": {17}}
    assert verified_matches([block], [record], {17: _course("Иное содержание")},
                            project_version_id=3) == {}
    assert verified_matches([_block("Другой профиль")], [record], {17: course},
                            project_version_id=3) == {}
    assert verified_matches([block], [record], {17: course}, project_version_id=4) == {}


def test_confirm_endpoint_uses_authenticated_author_and_rejects_stale_course():
    import asyncio
    from fastapi import HTTPException

    from app.api.projects import CoreConfirmationRequest, confirm_project_core_match
    from app.planner.core_evidence import block_content_hash, course_content_hash
    from app.models.course import Course
    from app.models.project import Project, ProjectVersion

    block, course = _block(), _course()
    project = SimpleNamespace(id=4, created_by=7, constraints_json={
        "curriculum_requirements": {"enabled": True, "core_blocks": [block]},
    })
    version = SimpleNamespace(id=3, project_id=4, version_number=1)

    class DB:
        def __init__(self):
            self.model = None
            self.commits = 0

        def query(self, model):
            self.model = model
            return self

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            return {Project: project, ProjectVersion: version, Course: course}[self.model]

        def commit(self):
            self.commits += 1

    db = DB()
    actor = SimpleNamespace(id=7, roles=[])
    values = {"project_version_id": 3, "block_id": "wood", "course_id": 17,
              "source_field": "description", "source_excerpt": "изделий из древесины",
              "rationale": "Проверено по описанию", "expected_course_hash": course_content_hash(course),
              "expected_block_hash": block_content_hash(block)}
    result = asyncio.run(confirm_project_core_match(4, CoreConfirmationRequest(**values), db, actor))
    assert result["confirmation"]["author_user_id"] == 7
    assert project.constraints_json["curriculum_confirmations"][0] == result["confirmation"]
    assert db.commits == 1

    with pytest.raises(HTTPException) as exc:
        asyncio.run(confirm_project_core_match(
            4, CoreConfirmationRequest(**{**values, "expected_course_hash": "0" * 64}), db, actor))
    assert exc.value.status_code == 409
    assert db.commits == 1
