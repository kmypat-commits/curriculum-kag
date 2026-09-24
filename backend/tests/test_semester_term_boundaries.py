import pytest

from app.planner.verifier import _semantic_min_semester
from app.planner.semester_rules import complexity_min_semester


@pytest.mark.parametrize("title", [
    "История культурологической науки",
    "Методика преподавания культурологических дисциплин",
    "Культурология",
])
def test_culture_is_not_urology(title):
    assert _semantic_min_semester(title, 8) == 1
    assert complexity_min_semester({"title": title}, 8) == 1


@pytest.mark.parametrize("title", ["Урология", "Клиническая урология", "Хирургия"])
def test_real_clinical_courses_keep_late_minimum(title):
    assert _semantic_min_semester(title, 8) == 5
    assert complexity_min_semester({"title": title}, 8) == 5
