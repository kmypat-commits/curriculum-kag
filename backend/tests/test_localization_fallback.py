from app.kag.scoring import _course_match_text
from app.models.course import Course
from app.services.content_localization import _course_translations


def test_scoring_does_not_load_legacy_translation_json_by_default():
    """The PostgreSQL path must not load the 58 MB legacy catalogue."""
    _course_translations.cache_clear()
    course = Course(
        title="Test course",
        description="Short description",
        topics=[],
        learning_outcomes=[],
    )

    _course_match_text(course)

    info = _course_translations.cache_info()
    assert info.misses == 0
    assert info.currsize == 0
