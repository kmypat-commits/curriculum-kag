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


def test_title_similarity_is_not_confirmation_of_mandatory_preparation():
    from app.services.epvo_repository import _assign_epvo_prerequisites
    foreign = NS(id=5029, title="Профессиональный иностранный язык",
                 domain="it", recommended_semester=4, credits=3,
                 prerequisites=[], topics=[])
    native = NS(id=734, title="Профессиональный казахский русский язык",
                domain="it", recommended_semester=5, credits=3,
                prerequisites=[], topics=[])
    assert _assign_epvo_prerequisites([foreign, native]) == 0
    assert native.prerequisites == []


def test_legacy_replace_flag_cannot_erase_reviewed_preparation():
    from app.services.epvo_repository import _assign_epvo_prerequisites
    foundation = NS(id=1, title="Математика", domain="science", recommended_semester=1,
                    credits=5, prerequisites=[], topics=[])
    advanced = NS(id=2, title="Физика", domain="science", recommended_semester=2,
                  credits=5, prerequisites=[foundation], topics=[])
    assert _assign_epvo_prerequisites([foundation, advanced], replace_existing=True) == 0
    assert advanced.prerequisites == [foundation]
