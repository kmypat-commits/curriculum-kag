from types import SimpleNamespace

import pytest

from app.planner import final_schedule_checks


@pytest.mark.parametrize("passed, scoped_ids, rejected", [
    (True, [6698], False),
    (True, [], True),
    (False, [6698], True),
])
def test_boundary_uses_only_successfully_audited_epvo_scope(
    monkeypatch, passed, scoped_ids, rejected,
):
    course = SimpleNamespace(id=6698, title="Общественное здоровье",
                             domain="it", prerequisites=[])
    db = SimpleNamespace(get=lambda model, cid: course)
    admission = {"passed": passed, "violations": [],
                 "checked_real_courses": 1, "scoped_course_ids": scoped_ids}
    # Isolate DB-backed admission; exercise the real domain boundary below.
    monkeypatch.setattr(final_schedule_checks, "audit_final_course_admission",
                        lambda schedule, version, session: admission)
    result = final_schedule_checks.audit_final_schedule_boundary(
        {1: [{"course_id": 6698, "title": course.title, "domain": "it", "credits": 5}]},
        db=db, project_version=SimpleNamespace(), project_domains=["Healthcare"],
        declared_secondary_domain="", is_project_domain=lambda item: False,
        is_general_course=lambda item: False,
    )
    assert bool(result["invalid_domain_courses"]) is rejected
    assert result["admission"]["passed"] is passed
