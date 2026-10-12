import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models.course import Course, CourseLocalization
from app.services.content_localization import register_course_translations


@pytest.mark.parametrize('source,status', [('manual','verified'),
    ('epvo','verified'),('machine_translation_gpt6_luna','needs_review'),
    ('automatic_course_draft','draft')])
def test_epvo_reimport_preserves_existing_reviewed_or_translated_text(source,status):
    engine=create_engine('sqlite:///:memory:')
    Course.__table__.create(engine)
    CourseLocalization.__table__.create(engine)
    with Session(engine) as db:
        course=Course(course_id='EPVO-42',title='Исходник',description='Описание',domain='IT',credits=5)
        db.add(course)
        db.flush()
        row=db.query(CourseLocalization).filter_by(course_id=course.id,language='en').one()
        row.title='Reviewed course'
        row.description='Reviewed description'
        row.source=source
        row.status=status
        db.flush()
        register_course_translations({course.id:{'title':{'en':'Replacement'},
            'description':{'en':'Replacement description'},'review_status':'verified_epvo',
            'source':'epvo_normalized_repository'}},db)
        db.expire(row)
        assert (row.title,row.description,row.source,row.status)==('Reviewed course','Reviewed description',source,status)
    engine.dispose()


def test_epvo_reimport_replaces_source_copy_but_keeps_translated_title():
    engine=create_engine('sqlite:///:memory:')
    Course.__table__.create(engine)
    CourseLocalization.__table__.create(engine)
    with Session(engine) as db:
        course=Course(course_id='EPVO-43',title='Исходник',description='Описание',domain='IT',credits=5)
        db.add(course)
        db.flush()
        row=db.query(CourseLocalization).filter_by(course_id=course.id,language='en').one()
        row.title='Existing translated title'
        db.flush()
        register_course_translations({course.id:{'title':{'en':'EPVO title'},
            'description':{'en':'Recovered description'},'review_status':'verified_epvo',
            'source':'epvo_normalized_repository'}},db)
        db.expire(row)
        assert row.title=='Existing translated title'
        assert row.description=='Recovered description'
    engine.dispose()
