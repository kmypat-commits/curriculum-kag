from types import SimpleNamespace as NS


def test_unrelated_epvo_titles_do_not_become_prerequisites_from_generic_descriptions():
    from app.services.epvo_repository import _assign_epvo_prerequisites

    generic = "Основные методы анализа данных и информационные технологии"
    earlier = NS(id=1, title="Основы кибербезопасности атомной энергетики",
                 description=generic, domain="it", recommended_semester=1,
                 credits=5, prerequisites=[], topics=[])
    later = NS(id=2, title="Глобальное здоровье", description=generic,
               domain="it", recommended_semester=3, credits=5,
               prerequisites=[], topics=[])
    assert _assign_epvo_prerequisites([earlier, later]) == 0
    assert later.prerequisites == []
