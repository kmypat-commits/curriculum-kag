import pytest
from sqlalchemy import create_engine, text

from scripts.apply_localization_batch import prepare_batch, apply_prepared


def test_translation_import_replaces_only_source_copies_and_preserves_verified_fields():
    engine = create_engine('sqlite://')
    with engine.begin() as db:
        db.execute(text('CREATE TABLE courses (id INTEGER PRIMARY KEY, title TEXT, description TEXT)'))
        db.execute(text('CREATE TABLE course_localizations (id INTEGER PRIMARY KEY, course_id INTEGER, language TEXT, title TEXT, description TEXT, source TEXT, status TEXT)'))
        db.execute(text("INSERT INTO courses VALUES (1,'Исходный курс','Исходное описание')"))
        db.execute(text("INSERT INTO course_localizations VALUES (10,1,'kk','Исходный курс','Исходное описание','automatic_course_draft','draft'), (11,1,'en','Verified title','Verified description','manual','verified')"))
        rows = [dict(course_id=1, language=lang, source_title='Исходный курс',
                     source_description='Исходное описание', title='Translated title',
                     description='Translated description', translator='gpt-6-luna') for lang in ('kk','en')]
        changes, skipped = prepare_batch(db, rows)
        assert len(changes) == 1
        assert len(skipped) == 1
        assert apply_prepared(db, changes) == 1
        saved = db.execute(text('SELECT * FROM course_localizations ORDER BY id')).mappings().all()
        assert saved[0]['title'] == 'Translated title'
        assert saved[0]['status'] == 'needs_review'
        assert saved[1]['title'] == 'Verified title'
        assert saved[1]['description'] == 'Verified description'
        assert db.execute(text('SELECT count(*) FROM courses')).scalar() == 1
    engine.dispose()


def test_changed_source_aborts_translation_before_any_write():
    engine = create_engine('sqlite://')
    with engine.begin() as db:
        db.execute(text('CREATE TABLE courses (id INTEGER PRIMARY KEY, title TEXT, description TEXT)'))
        db.execute(text('CREATE TABLE course_localizations (id INTEGER PRIMARY KEY, course_id INTEGER, language TEXT, title TEXT, description TEXT, source TEXT, status TEXT)'))
        db.execute(text("INSERT INTO courses VALUES (1,'Current','Description')"))
        with pytest.raises(ValueError, match='source_changed'):
            prepare_batch(db, [dict(course_id=1, language='kk', source_title='Old',
                                   source_description='Description', title='Жаңа', description='Сипаттама')])
    engine.dispose()


def test_damaged_source_is_not_silently_reconstructed_by_translation():
    engine = create_engine('sqlite://')
    with engine.begin() as db:
        db.execute(text('CREATE TABLE courses (id INTEGER PRIMARY KEY, title TEXT, description TEXT)'))
        db.execute(text('CREATE TABLE course_localizations (id INTEGER PRIMARY KEY, course_id INTEGER, language TEXT, title TEXT, description TEXT, source TEXT, status TEXT)'))
        db.execute(text("INSERT INTO courses VALUES (1,'Курс','Повреждённое �� описание')"))
        db.execute(text("INSERT INTO course_localizations VALUES (10,1,'kk','Курс','Повреждённое �� описание','automatic_course_draft','draft')"))
        changes, skipped = prepare_batch(db, [dict(course_id=1, language='kk',
            source_title='Курс', source_description='Повреждённое �� описание',
            title='Пән', description='Таза қалпына келтірілген мәтін')])
        assert changes == []
        assert skipped[0]['reason'] == 'damaged_source'
    engine.dispose()
