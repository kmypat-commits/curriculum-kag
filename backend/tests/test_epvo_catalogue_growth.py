from types import SimpleNamespace
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.course import Course
from app.models.epvo import EpvoDisciplineNormalized
from app.services import epvo_repository
from app.services.epvo_repository import approve_epvo_candidates


def test_generation_does_not_promote_new_epvo_courses_into_shared_catalogue():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    version = SimpleNamespace(
        project=SimpleNamespace(title='Algorithms', goal='Algorithms', domain1='ICT', domain2='',
            constraints_json={'education_level': 'bachelor', 'group_code': 'B057',
                              'direction_code': '6B061'}), learning_outcomes=[])
    with Session(engine) as db:
        db.add(EpvoDisciplineNormalized(canonical_title='Algorithms', title_ru='Algorithms',
            direction_codes=['6B061'], group_codes=['B057'], dedup_fingerprint='test',
            typical_credits=5, content_json={'description_ru': 'Algorithms'}))
        db.commit()
        result = approve_epvo_candidates(version, db)
        db.commit()
        assert result['created'] == 0
        assert db.query(Course).count() == 0
        assert db.query(EpvoDisciplineNormalized).one().approved_course_id is None


def test_generation_still_uses_existing_catalogue_course():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    version = SimpleNamespace(
        project=SimpleNamespace(title='Algorithms', goal='Algorithms', domain1='ICT', domain2='',
            constraints_json={'education_level': 'bachelor', 'group_code': 'B057',
                              'direction_code': '6B061'}), learning_outcomes=[])
    with Session(engine) as db:
        db.add(Course(course_id='EPVO-1', title='Algorithms', domain='ICT', credits=5))
        db.add(EpvoDisciplineNormalized(id=1, canonical_title='Algorithms', title_ru='Algorithms',
            direction_codes=['6B061'], group_codes=['B057'], dedup_fingerprint='test',
            typical_credits=5, content_json={'description_ru': 'Algorithms'}))
        db.commit()
        result = approve_epvo_candidates(version, db)
        assert result['linked'] == 1
        assert result['created'] == 0
        assert db.query(Course).count() == 1


def test_control_run_blocks_other_course_creation_paths_and_releases_guard():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        with epvo_repository.fixed_control_catalogue(db):
            db.add(Course(course_id='GOSO-NEW', title='New', domain='general', credits=5))
            with pytest.raises(RuntimeError, match='control_catalogue_missing_course'):
                db.flush()
            db.rollback()
        assert db.query(Course).count() == 0
        db.add(Course(course_id='MANUAL', title='Manual', domain='general', credits=5))
        db.commit()
        assert db.query(Course).count() == 1
