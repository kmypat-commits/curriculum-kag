from types import SimpleNamespace as NS
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.kag.scoring import _lightweight_candidate_courses, _extend_with_prerequisites, LARGE_CATALOG_RETRIEVAL_LIMIT


def test_lo_and_candidates_are_reencoded_together_after_encoder_failure(monkeypatch):
    import numpy as np
    from app.config import settings
    from app.kag.embedding_service import EmbeddingService
    from app.kag import scoring

    class Model:
        device = 'cpu'

        def encode(self, text, **kwargs):
            if isinstance(text, list):
                raise RuntimeError('candidate batch failure')
            return np.ones(settings.EMBEDDING_DIMENSION, dtype=np.float32)

    service = EmbeddingService()
    service._load_attempted = True
    service.model = Model()
    previous_lo = service.encode('learning outcome')
    monkeypatch.setattr(scoring, 'embedding_service', service)
    lo_vector, candidates = scoring._encode_match_frontier('learning outcome', ['course text'])
    fallback = EmbeddingService()
    fallback._load_attempted = True
    assert not np.array_equal(lo_vector, previous_lo)
    assert np.array_equal(lo_vector, fallback.encode('learning outcome'))
    assert np.array_equal(candidates[0], fallback.encode('course text'))


def test_expert_prefetch_limits_materialized_rows_per_discipline_without_changing_evidence():
    from sqlalchemy import event
    from app.kag.scoring import _prefetch_epvo_expert_links
    from app.models.epvo import EpvoDisciplineNormalized, EpvoDisciplineLoLink

    engine = create_engine("sqlite://")
    for model in (EpvoDisciplineNormalized, EpvoDisciplineLoLink):
        model.__table__.create(engine)
    loaded = []

    def record_load(link, _context):
        loaded.append(link.id)

    event.listen(EpvoDisciplineLoLink, "load", record_load)
    try:
        with Session(engine) as db:
            db.add_all([
                EpvoDisciplineNormalized(id=11, canonical_title="Первый", dedup_fingerprint="one"),
                EpvoDisciplineNormalized(id=12, canonical_title="Второй", dedup_fingerprint="two"),
            ])
            for discipline in (11, 12):
                for number in reversed(range(1, 41)):
                    db.add(EpvoDisciplineLoLink(id=discipline * 100 + number,
                        discipline_id=discipline, program_source_id="fixture",
                        lo_source_key=str(number), strength=1.0))
            db.commit()
            db.expunge_all()
            _prefetch_epvo_expert_links([
                NS(id=101, course_id="EPVO-11"), NS(id=102, course_id="EPVO-12"),
            ], db)
            assert [row.id for row in db.info["epvo_expert_links_cache"][11]] == list(range(1101, 1133))
            assert [row.id for row in db.info["epvo_expert_links_cache"][12]] == list(range(1201, 1233))
            assert len(loaded) == 64, "Discarded expert links must not be materialized by the ORM"
    finally:
        event.remove(EpvoDisciplineLoLink, "load", record_load)
        engine.dispose()


def test_expert_signal_reads_source_lo_with_string_program_id():
    from app.kag.scoring import _epvo_expert_signal

    source_text = "Проектирует информационные системы для здравоохранения"
    link = NS(discipline_id=7704, program_source_id="14547", lo_source_key="64613",
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
    link = NS(discipline_id=22, program_source_id="14547", lo_source_key="64606",
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


def test_expert_retrieval_keeps_approved_alias_source_evidence():
    """An approved older normalized row must not lose its LO on deduplication."""
    from app.models.epvo import EpvoDisciplineNormalized, EpvoDisciplineLoLink, RawEpvoLearningOutcome
    from app.kag.scoring import _expert_candidate_rows, _epvo_expert_signal

    engine = create_engine("sqlite://")
    for model in (EpvoDisciplineNormalized, EpvoDisciplineLoLink, RawEpvoLearningOutcome):
        model.__table__.create(engine)
    text = "Стандарты производства бетона составы строительных растворов свойства железобетона"
    courses = [NS(id=31302, course_id="EPVO-162857")]
    lo = NS(id=13, lo_text=text)
    with Session(engine) as db:
        db.add_all([
            EpvoDisciplineNormalized(id=1247, canonical_title="Строительные растворы",
                                     dedup_fingerprint="older", approved_course_id=31302),
            EpvoDisciplineNormalized(id=162857, canonical_title="Строительные растворы",
                                     dedup_fingerprint="canonical", approved_course_id=31302),
            RawEpvoLearningOutcome(program_source_id="2124", source_key="12278",
                                   payload_json={"learningOutcomeNameRu": text}, checksum="fixture"),
            EpvoDisciplineLoLink(discipline_id=1247, program_source_id="2124",
                                 lo_source_key="12278", strength=1.0),
        ])
        db.commit()
        rows = _expert_candidate_rows(lo, courses, db, limit=10)
        assert [row["course_id"] for row in rows] == [31302]
        signal = _epvo_expert_signal(courses[0], lo, db)
        assert signal["score"] == 1.0
        assert signal["source_program_id"] == "2124"
        assert signal["source_discipline_id"] == 1247
    engine.dispose()


def test_expert_alias_does_not_override_another_canonical_course():
    """A conflicting approval cannot donate another canonical course's evidence."""
    from app.models.epvo import EpvoDisciplineNormalized, EpvoDisciplineLoLink, RawEpvoLearningOutcome
    from app.kag.scoring import _expert_candidate_rows

    engine = create_engine("sqlite://")
    for model in (EpvoDisciplineNormalized, EpvoDisciplineLoLink, RawEpvoLearningOutcome):
        model.__table__.create(engine)
    text = "Concrete manufacturing standards and reinforced concrete properties"
    courses = [NS(id=31302, course_id="EPVO-162857"), NS(id=40000, course_id="EPVO-1247")]
    with Session(engine) as db:
        db.add_all([
            EpvoDisciplineNormalized(id=1247, canonical_title="Concrete",
                                     dedup_fingerprint="conflict", approved_course_id=31302),
            RawEpvoLearningOutcome(program_source_id="2124", source_key="12278",
                                   payload_json={"text": text}, checksum="fixture"),
            EpvoDisciplineLoLink(discipline_id=1247, program_source_id="2124",
                                 lo_source_key="12278", strength=1.0),
        ])
        db.commit()
        rows = _expert_candidate_rows(NS(id=13, lo_text=text), courses, db, limit=10)
        assert [row["course_id"] for row in rows] == [40000]
    engine.dispose()


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
