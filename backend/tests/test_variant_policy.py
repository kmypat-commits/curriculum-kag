"""Pure tests for the extracted variant-selection policy."""

from types import SimpleNamespace

from app.planner.variant_policy import (
    foreign_scope_conflict,
    project_domain_index,
    scope_rank,
    semester_stability_rank,
)


def _course(**values):
    defaults = {
        "id": 1,
        "course_id": "EPVO-1",
        "title": "Data analysis",
        "description": "Applied information systems and data",
        "domain": "Information and communication technologies",
        "credits": 5,
        "recommended_semester": 2,
        "cycle_component": "elective",
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_policy_prefers_explicit_domain_before_epvo_fallback():
    course = _course(domain="Medicine", id=17)
    assert project_domain_index(course, ["Information technologies", "Medicine"], {17: 0}) == 1


def test_policy_scope_rank_prefers_stable_course_id_evidence():
    course = _course(id=17, title="Same title")
    assert scope_rank(course, {17: 3}, {"same title": 1}) == 3


def test_policy_rejects_foreign_professional_scope():
    course = _course(title="Clinical pharmacology", description="Patient treatment")
    assert foreign_scope_conflict(course, "Information and communication technologies")


def test_policy_semester_stability_rewards_narrow_epvo_range():
    course = _course(course_id="EPVO-17")
    assert semester_stability_rank(course, {17: [2, 2, 3]}) > semester_stability_rank(course, {17: [1, 6]})
