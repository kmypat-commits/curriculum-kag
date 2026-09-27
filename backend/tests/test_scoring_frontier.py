from types import SimpleNamespace as NS

from app.kag.scoring import _lightweight_candidate_courses, _extend_with_prerequisites, LARGE_CATALOG_RETRIEVAL_LIMIT


def test_expert_signal_reads_source_lo_with_string_program_id():
    from app.kag.scoring import _epvo_expert_signal

    source_text = "Проектирует информационные системы для здравоохранения"
    link = NS(program_source_id="14547", lo_source_key="64613",
              expert_level="strong", strength=1.0)
    db = NS(info={
        "epvo_raw_lo_text_cache": {(14547, "64613"): source_text},
        "epvo_raw_lo_text_cache_loaded": True,
        "epvo_expert_links_cache": {7704: [link]},
    })
    course = NS(course_id="EPVO-7704")
    lo = NS(id=99, lo_text=source_text)
    assert _epvo_expert_signal(course, lo, db)["score"] >= 0.5


def test_expert_retrieval_recovers_source_link_missed_by_lexical_search():
    from app.kag.scoring import _expert_candidate_rows

    source_text = "Производит расчеты при проектировании производственных процессов"
    link = NS(program_source_id="14547", lo_source_key="64606",
              expert_level="strong", strength=1.0)
    db = NS(info={
        "epvo_raw_lo_text_cache": {("14547", "64606"): source_text},
        "epvo_raw_lo_text_cache_loaded": True,
        "epvo_expert_links_cache": {22: [link]},
    })
    courses = [NS(id=505, course_id="EPVO-22"), NS(id=521, course_id="EPVO-511")]
    lo = NS(id=2, lo_text=source_text)
    rows = _expert_candidate_rows(lo, courses, db, limit=10)
    assert [row["course_id"] for row in rows] == [505]
    assert rows[0]["retrieval_score"] >= 0.5


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


def test_scoring_frontier_includes_whole_scoped_parent_chain():
    roots = [{"course_id": 30, "retrieval_score": 9.0}]
    parents = {30: (20,), 20: (10,), 10: ()}
    expanded = _extend_with_prerequisites(roots, parents, {10, 20, 30})
    assert [row["course_id"] for row in expanded] == [30, 10, 20]
    assert roots == [{"course_id": 30, "retrieval_score": 9.0}]


def test_scoring_frontier_does_not_import_parent_outside_scope():
    roots = [{"course_id": 30, "retrieval_score": 9.0}]
    assert _extend_with_prerequisites(roots, {30: (20,)}, {30}) == roots
