from types import SimpleNamespace

from app.services.epvo_repository import is_required_catalogue_anchor


def row(title: str):
    return SimpleNamespace(
        canonical_title=title,
        title_ru=title,
        title_kk=None,
        title_en=None,
        content_json={},
    )


DOCTORAL_ICT = {
    "education_level": "doctorate",
    "direction_code": "8D061",
    "group_code": "D094",
}


def test_doctoral_ict_anchor_retains_real_project_management_course():
    assert is_required_catalogue_anchor(row("Управление ИТ проектами"), DOCTORAL_ICT)


def test_anchor_does_not_admit_generic_management_or_other_levels():
    assert not is_required_catalogue_anchor(row("Современная теория управления"), DOCTORAL_ICT)
    assert not is_required_catalogue_anchor(
        row("Управление ИТ проектами"),
        {**DOCTORAL_ICT, "education_level": "master"},
    )
