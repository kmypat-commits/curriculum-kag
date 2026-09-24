from types import SimpleNamespace as NS

from app.kag.scoring import _lightweight_candidate_courses, LARGE_CATALOG_RETRIEVAL_LIMIT


def course(i, title):
    return NS(id=i, title=title, domain="", recommended_semester=1, credits=5,
              description="", topics=[], learning_outcomes=[])


def test_relevant_course_beyond_old_prefix_is_retrieved():
    rows = [course(i, "Unrelated course") for i in range(LARGE_CATALOG_RETRIEVAL_LIMIT)]
    rows.append(course(99999, "International trade decisions"))
    result = _lightweight_candidate_courses(NS(lo_text="International trade decisions"), rows, 1)
    assert result[0]["course_id"] == 99999


def test_frontier_uses_course_content_not_only_title():
    relevant = course(99, "International economics")
    relevant.description = "Optimal decisions concerning foreign economic relations"
    distractor = course(1, "Optimal decisions in games")
    result = _lightweight_candidate_courses(
        NS(lo_text="Optimal decisions concerning foreign economic relations"),
        [distractor, relevant], 1,
    )
    assert result[0]["course_id"] == 99


def test_frontier_uses_localized_description():
    relevant = course(99, "International economics")
    result = _lightweight_candidate_courses(
        NS(lo_text="Внешнеэкономических связей"),
        [course(1, "Unrelated"), relevant], 1,
        {99: {"description_translations": {"ru": "Анализ внешнеэкономических связей"}}},
    )
    assert result[0]["course_id"] == 99


def test_retrieval_ties_are_independent_of_database_row_order():
    rows = [course(2, "Economics"), course(1, "Economics")]
    lo = NS(lo_text="Economics")
    assert _lightweight_candidate_courses(lo, rows, 1) == _lightweight_candidate_courses(lo, list(reversed(rows)), 1)
