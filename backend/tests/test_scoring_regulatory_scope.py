from types import SimpleNamespace

from app.kag.scoring import _domain_matches


def test_regulatory_language_is_scored_for_professional_programme():
    course = SimpleNamespace(course_id="GOSO-KZ-FOREIGN_1", domain="general")
    assert _domain_matches(course, ["water resources"])


def test_unrelated_nonregulatory_course_is_not_admitted_by_this_rule():
    course = SimpleNamespace(course_id="EPVO-123", domain="medicine")
    assert not _domain_matches(course, ["water resources"])


def test_unscoped_retrieval_still_allows_catalogue():
    assert _domain_matches(SimpleNamespace(course_id="LOCAL-1", domain="general"), [])
