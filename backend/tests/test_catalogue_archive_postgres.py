"""Opt-in integration against an explicitly disposable PostgreSQL database."""
import os

import pytest
from sqlalchemy import create_engine, text

from app.database import Base, engine as application_engine
from app.models.course import Course
from app.models.epvo import EpvoDisciplineNormalized
from scripts.archive_catalogue_to_snapshot import archive, protected_snapshot, restore


@pytest.mark.skipif(os.environ.get('CATALOGUE_ARCHIVE_POSTGRES_TEST') != '1', reason='disposable PostgreSQL integration')
def test_archive_preserves_foreign_links_and_rolls_back_failed_guard():
    url = application_engine.url.set(database='curriculum_catalogue_archive_test_20261022')
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(Course.__table__.insert(), [
            {'id': 1, 'course_id': 'KEEP', 'title': 'Keep', 'domain': 'IT', 'credits': 5},
            {'id': 2, 'course_id': 'EPVO-2', 'title': 'Archive', 'domain': 'IT', 'credits': 5},
        ])
        c.execute(text("INSERT INTO course_localizations(course_id,language,title,source,status) VALUES (2,'en','Reviewed','manual','verified')"))
        c.execute(text("INSERT INTO course_chunks(id,course_id,chunk_type,chunk_text) VALUES (2,2,'description','Source')"))
        c.execute(text("INSERT INTO embeddings(chunk_id,model_version) VALUES (2,'test')"))
        c.execute(EpvoDisciplineNormalized.__table__.insert(),
                  {'id': 2, 'canonical_title': 'Archive', 'dedup_fingerprint': '2',
                   'approved_course_id': 2, 'status': 'approved'})
    # A failed validation must undo all DDL, updates and cascade deletes.
    with pytest.raises(AssertionError), engine.begin() as c:
        plan = {'archive_ids': [2], 'archived': 1, 'retained': 99,
                'protected_sha256': protected_snapshot(c)}
        archive(c, plan, 'catalogue_archive_failed')
    with engine.begin() as c:
        assert c.execute(text('select count(*) from courses')).scalar_one() == 2
        assert c.execute(text("select to_regnamespace('catalogue_archive_failed')")).scalar_one() is None
        plan = {'archive_ids': [2], 'archived': 1, 'retained': 1,
                'protected_sha256': protected_snapshot(c)}
        counts = archive(c, plan, 'catalogue_archive_test')
        assert counts['courses'] == 1 and counts['embeddings'] == 1
    with engine.connect() as c:
        assert c.execute(text('select id from courses')).scalar_one() == 1
        assert c.execute(text('select approved_course_id from epvo_disciplines_normalized')).scalar_one() is None
        assert c.execute(text('select source from catalogue_archive_test.course_localizations')).scalar_one() == 'manual'
        assert c.execute(text('select count(*) from embeddings')).scalar_one() == 0
    with engine.begin() as c:
        counts = restore(c, 'catalogue_archive_test')
        assert counts['courses'] == 1
    with engine.connect() as c:
        assert c.execute(text('select count(*) from courses')).scalar_one() == 2
        assert c.execute(text('select approved_course_id from epvo_disciplines_normalized')).scalar_one() == 2
        assert c.execute(text("select source,status,title from course_localizations where course_id=2")).one() == ('manual','verified','Reviewed')
        assert c.execute(text('select count(*) from embeddings')).scalar_one() == 1
    with pytest.raises(RuntimeError, match='identity already exists'), engine.begin() as c:
        restore(c, 'catalogue_archive_test')
    engine.dispose()
