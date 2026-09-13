"""Pure tests for the extracted variant-selection policy."""

from types import SimpleNamespace

from app.planner.variant_policy import (
    build_domain_policy_callbacks,
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


def test_domain_callbacks_use_loaded_epvo_scope_evidence():
    """A scoped secondary-domain share must not be lost after index loading."""
    course = _course(id=42, domain="Unmapped catalogue label")
    domain_index, domain_share = build_domain_policy_callbacks(
        project_domains=["Law", "Information technologies"],
        epvo_domain_index={42: 2},
        epvo_domain_shares={42: (0.25, 0.75)},
    )

    assert domain_index(course) == 1
    assert domain_share(course, 0) == 0.25
    assert domain_share(course, 1) == 0.75


def test_policy_scope_rank_prefers_stable_course_id_evidence():
    course = _course(id=17, title="Same title")
    assert scope_rank(course, {17: 3}, {"same title": 1}) == 3


def test_policy_rejects_foreign_professional_scope():
    course = _course(title="Clinical pharmacology", description="Patient treatment")
    assert foreign_scope_conflict(course, "Information and communication technologies")


def test_policy_semester_stability_rewards_narrow_epvo_range():
    course = _course(course_id="EPVO-17")
    assert semester_stability_rank(course, {17: [2, 2, 3]}) > semester_stability_rank(course, {17: [1, 6]})
