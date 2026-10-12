from types import SimpleNamespace

from app.planner.scheduler_domain_rules import has_foreign_professional_title


def test_explicit_wood_industry_economics_is_not_foreign_to_manufacturing():
    course = SimpleNamespace(
        title='Экономика и менеджмент I (в мебельной и деревообрабатывающей промышленности)',
        domain='it',
    )
    assert not has_foreign_professional_title(course, ['Производственные и обрабатывающие отрасли'])


def test_generic_enterprise_management_stays_foreign_to_manufacturing():
    course = SimpleNamespace(title='Экономика предприятия', domain='it')
    assert has_foreign_professional_title(course, ['Производственные и обрабатывающие отрасли'])


def test_wood_industry_economics_stays_foreign_to_unrelated_medical_programme():
    course = SimpleNamespace(title='Экономика деревообрабатывающей промышленности', domain='it')
    assert has_foreign_professional_title(course, ['Здравоохранение'])
