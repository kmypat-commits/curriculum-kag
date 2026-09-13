from types import SimpleNamespace

from app.planner.scheduler_domain_rules import find_invalid_project_domain_courses


class _Db:
    def __init__(self, courses):
        self.courses = courses

    def get(self, _model, course_id):
        return self.courses.get(course_id)


def test_law_it_forensics_is_not_a_false_foreign_domain_violation():
    course = SimpleNamespace(
        id=42,
        title="Цифровая криминалистика и судебная экспертиза",
        domain="Forensics",
        prerequisites=[],
    )
    invalid = find_invalid_project_domain_courses(
        {1: [{"course_id": 42, "domain": "Forensics"}]},
        _Db({42: course}),
        ["Право", "Информационно-коммуникационные технологии"],
        "информационно-коммуникационные технологии",
        is_project_domain=lambda _course: False,
    )

    assert invalid == []


def test_forensics_stays_blocked_without_the_law_it_pairing():
    course = SimpleNamespace(
        id=43,
        title="Судебная экспертиза",
        domain="Forensics",
        prerequisites=[],
    )
    invalid = find_invalid_project_domain_courses(
        {1: [{"course_id": 43, "domain": "Forensics"}]},
        _Db({43: course}),
        ["Экономика", "Информационно-коммуникационные технологии"],
        "информационно-коммуникационные технологии",
        is_project_domain=lambda _course: False,
    )

    assert invalid == [{"course_id": 43, "title": "Судебная экспертиза", "domain": "Forensics"}]
