import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.course import Course, CourseLocalization
from app.models.university_baseline import UniversityBaselineImport
from app.models.project import Project, ProjectVersion
from app.services.university_baseline import confirm_import, course_content_hash, load_revision


@pytest.fixture
def baseline_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Project.__table__, ProjectVersion.__table__, Course.__table__, CourseLocalization.__table__, UniversityBaselineImport.__table__])
    # Revision table is added explicitly after imports so the FK graph stays small.
    from app.models.university_baseline import UniversityBaselineRevision
    Base.metadata.create_all(engine, tables=[UniversityBaselineRevision.__table__])
    db = sessionmaker(bind=engine)()
    course = Course(course_id="CS-1", title="Algorithms", domain="D1", credits=5, description="Intro")
    project = Project(title="P", domain1="D1", domain2="D2")
    db.add_all([project, course])
    db.flush()
    version = ProjectVersion(project_id=project.id, version_number=1)
    db.add(version)
    db.flush()
    imported = UniversityBaselineImport(project_version_id=version.id, created_by=11, source_name="x.csv", source_sha256="src", source_bytes=10, rows_json=[{"source_row": 2, "original_code": "CS-1", "original_title": "Algorithms", "credits": 5.0, "content_sha256": course_content_hash(course)}], mapping_json={"2": course.id}, status="ready")
    db.add(imported)
    db.commit()
    yield db, imported.id, course.id
    db.close()


def test_confirmation_is_idempotent(baseline_db):
    db, import_id, _ = baseline_db
    first = confirm_import(db, import_id, 11)
    db.commit()
    second = confirm_import(db, import_id, 11)
    assert first.id == second.id
    assert second.revision_number == 1


def test_stale_mapping_rejects_confirmation(baseline_db):
    db, import_id, course_id = baseline_db
    db.query(Course).filter(Course.id == course_id).update({"description": "Changed"})
    db.commit()
    with pytest.raises(ValueError, match="mapping_stale"):
        confirm_import(db, import_id, 11)


def test_revision_is_scoped_to_project_version(baseline_db):
    db, import_id, _ = baseline_db
    revision = confirm_import(db, import_id, 11)
    db.commit()
    assert load_revision(db, revision.project_version_id, revision.id).id == revision.id
    with pytest.raises(ValueError, match="not_found"):
        load_revision(db, revision.project_version_id + 100, revision.id)
