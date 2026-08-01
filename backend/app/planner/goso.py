"""Kazakhstan ГОСО rules extracted from the supplied 2026 normative document."""
from __future__ import annotations

from typing import Dict, List

from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.project import LearningOutcome, ProjectVersion


GOSO_DISPLAY_TITLES = {
    "HISTORY_KZ": "История Казахстана", "PHILOSOPHY": "Философия",
    "KZ_RU_1": "Казахский (русский) язык 1", "KZ_RU_2": "Казахский (русский) язык 2",
    "FOREIGN_1": "Иностранный язык 1", "FOREIGN_2": "Иностранный язык 2",
    "ICT": "Информационно-коммуникационные технологии",
    "SOCIAL_POLITICAL": "Модуль социально-политических знаний",
    "PHYSICAL_1": "Физическая культура 1", "PHYSICAL_2": "Физическая культура 2",
    "OOD_UNIVERSITY": "Основы права и академической добропорядочности",
    "PROFESSIONAL_PRACTICE": "Профессиональная практика",
    "BACHELOR_FINAL_ATTESTATION": "Написание и защита дипломной работы (проекта) или комплексный экзамен",
    "HISTORY_PHIL_SCIENCE": "История и философия науки", "PROF_FOREIGN": "Профессиональный иностранный язык",
    "HIGHER_PEDAGOGY": "Педагогика высшей школы", "MANAGEMENT_PSYCHOLOGY": "Психология управления",
    "PEDAGOGICAL_PRACTICE": "Педагогическая практика", "RESEARCH_PRACTICE": "Исследовательская практика",
    "NIRM_1": "Научно-исследовательская работа магистранта 1", "NIRM_2": "Научно-исследовательская работа магистранта 2",
    "NIRM_3": "Научно-исследовательская работа магистранта 3", "NIRM_4": "Научно-исследовательская работа магистранта 4",
    "FINAL_ATTESTATION": "Оформление и защита магистерской диссертации",
    "MASTER_PRODUCTION_PRACTICE": "Производственная практика магистранта",
    "EIRM_PROFILE_60": "Экспериментально-исследовательская работа магистранта",
    "EIRM_PROFILE_90": "Экспериментально-исследовательская работа магистранта",
    "MASTER_PROJECT_FINAL": "Оформление и защита магистерского проекта",
    "DOCTORAL_PEDAGOGICAL_PRACTICE": "Педагогическая практика докторанта",
    "DOCTORAL_RESEARCH_PRACTICE": "Исследовательская практика докторанта",
    "DOCTORAL_PRODUCTION_PRACTICE": "Производственная практика докторанта",
    "NIRD_1": "Научно-исследовательская работа докторанта 1", "NIRD_2": "Научно-исследовательская работа докторанта 2",
    "NIRD_3": "Научно-исследовательская работа докторанта 3", "NIRD_4": "Научно-исследовательская работа докторанта 4",
    "NIRD_5": "Научно-исследовательская работа докторанта 5",
    "NIRD_6": "Научно-исследовательская работа докторанта, стажировка и завершение диссертации",
    "EIRD_1": "Экспериментально-исследовательская работа докторанта 1", "EIRD_2": "Экспериментально-исследовательская работа докторанта 2",
    "EIRD_3": "Экспериментально-исследовательская работа докторанта 3", "EIRD_4": "Экспериментально-исследовательская работа докторанта 4",
    "EIRD_5": "Экспериментально-исследовательская работа докторанта 5",
    "EIRD_6": "Экспериментально-исследовательская работа докторанта, стажировка и завершение диссертации",
    "DOCTORAL_FINAL_ATTESTATION": "Написание и защита докторской диссертации",
}


BACHELOR_ITEMS = [
    ("HISTORY_KZ", "История Казахстана", 5, 1, "goso_ood_mandatory", "Историческое развитие Казахстана, гражданская позиция и государственный экзамен."),
    ("PHILOSOPHY", "Философия", 5, 2, "goso_ood_mandatory", "Основы философского и научного познания, критическое мышление и мировоззрение."),
    ("KZ_RU_1", "Казахский (русский) язык 1", 5, 1, "goso_ood_mandatory", "Академическая, социальная и профессиональная коммуникация на языке обучения."),
    ("KZ_RU_2", "Казахский (русский) язык 2", 5, 2, "goso_ood_mandatory", "Продвинутая академическая и профессиональная коммуникация на языке обучения."),
    ("FOREIGN_1", "Иностранный язык 1", 5, 1, "goso_ood_mandatory", "Базовая академическая и профессиональная коммуникация на иностранном языке."),
    ("FOREIGN_2", "Иностранный язык 2", 5, 2, "goso_ood_mandatory", "Профессиональная коммуникация и работа с зарубежными источниками."),
    ("ICT", "Информационно-коммуникационные технологии", 5, 1, "goso_ood_mandatory", "Цифровая грамотность и применение современных информационно-коммуникационных технологий."),
    ("SOCIAL_POLITICAL", "Модуль социально-политических знаний", 8, 2, "goso_ood_mandatory", "Социология, политология, культурология и психология в общественной и профессиональной деятельности."),
    ("PHYSICAL_1", "Физическая культура 1", 4, 1, "goso_ood_mandatory", "Здоровый образ жизни, физическое развитие и безопасность жизнедеятельности."),
    ("PHYSICAL_2", "Физическая культура 2", 4, 2, "goso_ood_mandatory", "Физическое самосовершенствование и устойчивые практики здорового образа жизни."),
    ("OOD_UNIVERSITY", "Основы права и академической добропорядочности", 5, 3, "goso_ood_university", "Правовые, этические и антикоррупционные основы академической и профессиональной деятельности."),
]

MASTER_SCIENTIFIC_ITEMS = [
    ("HISTORY_PHIL_SCIENCE", "История и философия науки", 5, 1, "goso_bd_university", "История науки, методология научного познания и философские проблемы исследований."),
    ("PROF_FOREIGN", "Профессиональный иностранный язык", 5, 1, "goso_bd_university", "Профессиональная и научная коммуникация на иностранном языке."),
    ("HIGHER_PEDAGOGY", "Педагогика высшей школы", 5, 1, "goso_bd_university", "Методика преподавания, методы и технологии обучения в высшей школе."),
    ("MANAGEMENT_PSYCHOLOGY", "Психология управления", 5, 2, "goso_bd_university", "Психолого-педагогические и управленческие компетенции руководителя."),
    ("PEDAGOGICAL_PRACTICE", "Педагогическая практика", 5, 2, "goso_bd_practice", "Практические навыки преподавания и обучения в бакалавриате."),
    ("RESEARCH_PRACTICE", "Исследовательская практика", 5, 3, "goso_pd_practice", "Современные методы исследования, обработки и интерпретации данных."),
    ("NIRM_1", "Научно-исследовательская работа магистранта 1", 6, 1, "goso_research", "Постановка научной проблемы и планирование магистерского исследования."),
    ("NIRM_2", "Научно-исследовательская работа магистранта 2", 6, 2, "goso_research", "Методология, сбор данных и подготовка результатов исследования."),
    ("NIRM_3", "Научно-исследовательская работа магистранта 3", 6, 3, "goso_research", "Научная стажировка, анализ данных и публикация результатов."),
    ("NIRM_4", "Научно-исследовательская работа магистранта 4", 6, 4, "goso_research", "Завершение магистерской диссертации и подготовка к защите."),
    ("FINAL_ATTESTATION", "Оформление и защита магистерской диссертации", 8, 4, "goso_final", "Итоговая аттестация и защита магистерской диссертации."),
]

# Activities whose minimum aggregate volume is stated by the supplied ГОСО РК
# document (revision 04.05.2026).  Bachelor practice is part of the 176-credit
# BD/PD block; ГОСО does not prescribe its separate volume, therefore 6 credits
# below are an explicit planner allocation and not presented as a legal minimum.
BACHELOR_COMPLETION_ITEMS = [
    ("PROFESSIONAL_PRACTICE", "Профессиональная практика", 6, 7, "goso_bd_pd_practice", "Применение профессиональных знаний в организации. ГОСО включает практику в цикл БД/ПД, а отдельный объём определяет ОВПО; планировщик резервирует 6 кредитов."),
    ("BACHELOR_FINAL_ATTESTATION", "Написание и защита дипломной работы (проекта) или комплексный экзамен", 8, 8, "goso_final", "Итоговая аттестация бакалавриата. Нормативный минимум ГОСО РК — 8 академических кредитов."),
]

MASTER_PROFILE_60_ITEMS = [
    ("MASTER_PRODUCTION_PRACTICE", "Производственная практика магистранта", 5, 1, "goso_pd_practice", "Закрепление профессиональных компетенций. Отдельный объём практики определяет ОВПО внутри цикла ПД."),
    ("EIRM_PROFILE_60", "Экспериментально-исследовательская работа магистранта, включая стажировку и выполнение магистерского проекта", 13, 2, "goso_research", "ЭИРМ профильной магистратуры сроком 1 год. Нормативный минимум ГОСО РК — 13 кредитов."),
    ("MASTER_PROJECT_FINAL", "Оформление и защита магистерского проекта", 8, 2, "goso_final", "Итоговая аттестация профильной магистратуры. Нормативный минимум ГОСО РК — 8 кредитов."),
]

MASTER_PROFILE_90_ITEMS = [
    ("MASTER_PRODUCTION_PRACTICE", "Производственная практика магистранта", 5, 2, "goso_pd_practice", "Закрепление профессиональных компетенций. Отдельный объём практики определяет ОВПО внутри цикла ПД."),
    ("EIRM_PROFILE_90", "Экспериментально-исследовательская работа магистранта, включая стажировку и выполнение магистерского проекта", 18, 3, "goso_research", "ЭИРМ профильной магистратуры сроком 1,5 года. Нормативный объём ГОСО РК — 18 кредитов."),
    ("MASTER_PROJECT_FINAL", "Оформление и защита магистерского проекта", 8, 3, "goso_final", "Итоговая аттестация профильной магистратуры. Нормативный минимум ГОСО РК — 8 кредитов."),
]

DOCTORATE_SCIENTIFIC_ITEMS = [
    ("DOCTORAL_PEDAGOGICAL_PRACTICE", "Педагогическая практика докторанта", 10, 3, "goso_bd_practice", "Педагогическая практика научно-педагогической докторантуры — не менее 10 кредитов по ГОСО РК."),
    ("DOCTORAL_RESEARCH_PRACTICE", "Исследовательская практика докторанта", 10, 4, "goso_pd_practice", "Исследовательская практика научно-педагогической докторантуры — не менее 10 кредитов по ГОСО РК."),
    ("NIRD_1", "Научно-исследовательская работа докторанта 1", 20, 1, "goso_research", "Первый этап НИРД, входящий в нормативный объём 123 кредита."),
    ("NIRD_2", "Научно-исследовательская работа докторанта 2", 20, 2, "goso_research", "Второй этап НИРД, входящий в нормативный объём 123 кредита."),
    ("NIRD_3", "Научно-исследовательская работа докторанта 3", 20, 3, "goso_research", "Третий этап НИРД, входящий в нормативный объём 123 кредита."),
    ("NIRD_4", "Научно-исследовательская работа докторанта 4", 20, 4, "goso_research", "Четвёртый этап НИРД, входящий в нормативный объём 123 кредита."),
    ("NIRD_5", "Научно-исследовательская работа докторанта 5", 22, 5, "goso_research", "Пятый этап НИРД, входящий в нормативный объём 123 кредита."),
    ("NIRD_6", "Научно-исследовательская работа докторанта, стажировка и завершение диссертации", 21, 6, "goso_research", "Заключительный этап НИРД. Совокупный нормативный объём НИРД — 123 кредита."),
    ("DOCTORAL_FINAL_ATTESTATION", "Написание и защита докторской диссертации", 12, 6, "goso_final", "Итоговая аттестация докторантуры — 12 кредитов по ГОСО РК."),
]

DOCTORATE_PROFILE_ITEMS = [
    ("DOCTORAL_PRODUCTION_PRACTICE", "Производственная практика докторанта", 20, 4, "goso_pd_practice", "Производственная практика профильной докторантуры — не менее 20 кредитов по ГОСО РК."),
    *[(item[0].replace("NIRD_", "EIRD_"), item[1].replace("Научно-исследовательская", "Экспериментально-исследовательская").replace("НИРД", "ЭИРД"), *item[2:]) for item in DOCTORATE_SCIENTIFIC_ITEMS if item[0].startswith("NIRD_")],
    next(item for item in DOCTORATE_SCIENTIFIC_ITEMS if item[0] == "DOCTORAL_FINAL_ATTESTATION"),
]


GOSO_PROGRAM_LOS = {
    "bachelor": [
        ("LO-GOSO-B1", "Объяснять историческое развитие Казахстана и применять гражданские и социально-политические знания в профессиональной деятельности."),
        ("LO-GOSO-B2", "Осуществлять академическую и профессиональную коммуникацию на государственном, русском и иностранном языках."),
        ("LO-GOSO-B3", "Применять информационно-коммуникационные технологии и принципы цифровой грамотности для решения учебных и профессиональных задач."),
        ("LO-GOSO-B4", "Поддерживать безопасный и здоровый образ жизни, физическое саморазвитие и ответственное поведение."),
        ("LO-GOSO-B5", "Принимать правовые и этически обоснованные решения, соблюдая академическую добропорядочность и антикоррупционные нормы."),
        ("LO-GOSO-B6", "Применять профессиональные компетенции на практике и подтвердить достижение результатов программы в итоговой работе, проекте или комплексном экзамене."),
    ],
    "master": [
        ("LO-GOSO-M1", "Применять историю, философию и методологию науки при постановке и обосновании исследовательской проблемы."),
        ("LO-GOSO-M2", "Осуществлять профессиональную и научную коммуникацию на иностранном языке."),
        ("LO-GOSO-M3", "Применять педагогические, психологические и управленческие методы в высшем образовании и профессиональной деятельности."),
        ("LO-GOSO-M4", "Планировать и проводить самостоятельное исследование, анализировать данные и представлять научные результаты."),
        ("LO-GOSO-M5", "Подготовить, обосновать и публично защитить магистерскую диссертацию с соблюдением исследовательской этики."),
    ],
    "doctorate": [
        ("LO-GOSO-D1", "Создавать новое научное знание на основе современной методологии и критического анализа исследований."),
        ("LO-GOSO-D2", "Публиковать и представлять результаты исследования международному профессиональному сообществу."),
        ("LO-GOSO-D3", "Осуществлять преподавательскую и академическую лидерскую деятельность в высшем образовании."),
        ("LO-GOSO-D4", "Обеспечивать исследовательскую этику, воспроизводимость и академическую добропорядочность."),
        ("LO-GOSO-D5", "Подготовить и защитить докторскую диссертацию, содержащую обоснованный научный вклад."),
    ],
}

GOSO_COURSE_LO_CODES = {
    "HISTORY_KZ": "LO-GOSO-B1", "PHILOSOPHY": "LO-GOSO-B1", "SOCIAL_POLITICAL": "LO-GOSO-B1",
    "KZ_RU_1": "LO-GOSO-B2", "KZ_RU_2": "LO-GOSO-B2", "FOREIGN_1": "LO-GOSO-B2", "FOREIGN_2": "LO-GOSO-B2",
    "ICT": "LO-GOSO-B3", "PHYSICAL_1": "LO-GOSO-B4", "PHYSICAL_2": "LO-GOSO-B4", "OOD_UNIVERSITY": "LO-GOSO-B5",
    "PROFESSIONAL_PRACTICE": "LO-GOSO-B6", "BACHELOR_FINAL_ATTESTATION": "LO-GOSO-B6",
    "HISTORY_PHIL_SCIENCE": "LO-GOSO-M1", "PROF_FOREIGN": "LO-GOSO-M2",
    "HIGHER_PEDAGOGY": "LO-GOSO-M3", "MANAGEMENT_PSYCHOLOGY": "LO-GOSO-M3", "PEDAGOGICAL_PRACTICE": "LO-GOSO-M3",
    "RESEARCH_PRACTICE": "LO-GOSO-M4", "NIRM_1": "LO-GOSO-M4", "NIRM_2": "LO-GOSO-M4", "NIRM_3": "LO-GOSO-M4",
    "NIRM_4": "LO-GOSO-M5", "FINAL_ATTESTATION": "LO-GOSO-M5",
    "MASTER_PRODUCTION_PRACTICE": "LO-GOSO-M3", "EIRM_PROFILE_60": "LO-GOSO-M4", "EIRM_PROFILE_90": "LO-GOSO-M4", "MASTER_PROJECT_FINAL": "LO-GOSO-M5",
    "DOCTORAL_PEDAGOGICAL_PRACTICE": "LO-GOSO-D3", "DOCTORAL_RESEARCH_PRACTICE": "LO-GOSO-D1",
    "DOCTORAL_PRODUCTION_PRACTICE": "LO-GOSO-D1",
    "NIRD_1": "LO-GOSO-D1", "NIRD_2": "LO-GOSO-D1", "NIRD_3": "LO-GOSO-D2",
    "NIRD_4": "LO-GOSO-D2", "NIRD_5": "LO-GOSO-D4", "NIRD_6": "LO-GOSO-D5",
    "EIRD_1": "LO-GOSO-D1", "EIRD_2": "LO-GOSO-D1", "EIRD_3": "LO-GOSO-D2",
    "EIRD_4": "LO-GOSO-D2", "EIRD_5": "LO-GOSO-D4", "EIRD_6": "LO-GOSO-D5",
    "DOCTORAL_FINAL_ATTESTATION": "LO-GOSO-D5",
}

GOSO_PREREQUISITE_CODES = {
    "GOSO-KZ-KZ_RU_2": "GOSO-KZ-KZ_RU_1",
    "GOSO-KZ-FOREIGN_2": "GOSO-KZ-FOREIGN_1",
    "GOSO-KZ-PHYSICAL_2": "GOSO-KZ-PHYSICAL_1",
    "GOSO-KZ-NIRM_2": "GOSO-KZ-NIRM_1",
    "GOSO-KZ-NIRM_3": "GOSO-KZ-NIRM_2",
    "GOSO-KZ-NIRM_4": "GOSO-KZ-NIRM_3",
    "GOSO-KZ-FINAL_ATTESTATION": "GOSO-KZ-NIRM_4",
    "GOSO-KZ-BACHELOR_FINAL_ATTESTATION": "GOSO-KZ-PROFESSIONAL_PRACTICE",
    "GOSO-KZ-NIRD_2": "GOSO-KZ-NIRD_1",
    "GOSO-KZ-NIRD_3": "GOSO-KZ-NIRD_2",
    "GOSO-KZ-NIRD_4": "GOSO-KZ-NIRD_3",
    "GOSO-KZ-NIRD_5": "GOSO-KZ-NIRD_4",
    "GOSO-KZ-NIRD_6": "GOSO-KZ-NIRD_5",
    "GOSO-KZ-EIRD_2": "GOSO-KZ-EIRD_1",
    "GOSO-KZ-EIRD_3": "GOSO-KZ-EIRD_2",
    "GOSO-KZ-EIRD_4": "GOSO-KZ-EIRD_3",
    "GOSO-KZ-EIRD_5": "GOSO-KZ-EIRD_4",
    "GOSO-KZ-EIRD_6": "GOSO-KZ-EIRD_5",
}


def _applicable_goso_prerequisite_pairs(by_code: Dict[str, Course]) -> List[tuple[Course, Course]]:
    """Return only strict earlier-semester edges.

    Research work and dissertation defence may coexist in the final semester;
    that is a within-semester sequence, not a curriculum prerequisite edge.
    """
    result = []
    for child_code, parent_code in GOSO_PREREQUISITE_CODES.items():
        child, parent = by_code.get(child_code), by_code.get(parent_code)
        if (
            child
            and parent
            and int(parent.recommended_semester or 1) < int(child.recommended_semester or 1)
        ):
            result.append((child, parent))
    return result


def _definitions_for_constraints(constraints: Dict) -> List[tuple]:
    """Return only the ГОСО block applicable to this programme and track."""
    level = str(constraints.get("education_level") or "bachelor").lower()
    semesters = max(1, int(constraints.get("total_semesters") or 8))
    total_credits = int(constraints.get("total_credits") or 0)
    track = str(
        constraints.get("master_track")
        or constraints.get("doctorate_track")
        or constraints.get("education_track")
        or "scientific_pedagogical"
    ).lower()

    if level == "bachelor":
        definitions = [*BACHELOR_ITEMS, *BACHELOR_COMPLETION_ITEMS]
    elif level == "master":
        if track in {"profile", "professional", "specialized", "профильная"}:
            definitions = MASTER_PROFILE_90_ITEMS if total_credits >= 90 else MASTER_PROFILE_60_ITEMS
        else:
            definitions = MASTER_SCIENTIFIC_ITEMS
    elif level in {"doctorate", "doctoral", "phd"}:
        definitions = DOCTORATE_PROFILE_ITEMS if track in {"profile", "professional", "профильная"} else DOCTORATE_SCIENTIFIC_ITEMS
    else:
        return []

    final_codes = {"BACHELOR_FINAL_ATTESTATION", "FINAL_ATTESTATION", "MASTER_PROJECT_FINAL", "DOCTORAL_FINAL_ATTESTATION"}
    late_codes = {"PROFESSIONAL_PRACTICE"}
    adjusted = []
    for code, title, credits, semester, component, description in definitions:
        if code in final_codes:
            semester = semesters
        elif code in late_codes:
            semester = max(1, semesters - 1)
        else:
            semester = min(int(semester), semesters)
        adjusted.append((code, title, credits, semester, component, description))
    return adjusted


def ensure_goso_learning_outcomes(version: ProjectVersion, db: Session) -> List[LearningOutcome]:
    """Add explicit programme outcomes required to justify mandatory ГОСО units."""
    constraints = version.project.constraints_json or {}
    if str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() != "KZ":
        return []
    level = str(constraints.get("education_level") or "bachelor").lower()
    definitions = GOSO_PROGRAM_LOS.get(level, [])
    existing = {lo.lo_code: lo for lo in version.learning_outcomes}
    next_order = max((int(lo.order_index or 0) for lo in version.learning_outcomes), default=0) + 1
    result = []
    for code, text in definitions:
        lo = existing.get(code)
        if lo is None:
            lo = LearningOutcome(
                project_version_id=version.id,
                lo_code=code,
                lo_text=text,
                taxonomy_level="apply",
                weight=1.0,
                order_index=next_order,
            )
            next_order += 1
            db.add(lo)
        else:
            lo.lo_text = text
        result.append(lo)
    db.flush()
    db.expire(version, ["learning_outcomes"])
    return result


def _upsert_course(db: Session, code: str, title: str, credits: int, semester: int, component: str, description: str) -> Course:
    stable_code = f"GOSO-KZ-{code}"
    course = db.query(Course).filter(Course.course_id == stable_code).first()
    values = {
        "title": title,
        "domain": "general_goso_kz",
        "credits": credits,
        "recommended_semester": semester,
        "description": description,
        "topics": [],
        "learning_outcomes": [],
        "assessment_methods": ["экзамен", "практические задания"],
        "language": "ru",
        "cycle_component": component,
    }
    if course is None:
        course = Course(course_id=stable_code, **values)
        db.add(course)
        db.flush()
    else:
        for key, value in values.items():
            setattr(course, key, value)
    return course


def ensure_goso_items(version: ProjectVersion, db: Session) -> List[Dict]:
    constraints = version.project.constraints_json or {}
    if str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() != "KZ":
        return []
    definitions = _definitions_for_constraints(constraints)
    if not definitions:
        return []
    goso_los = {lo.lo_code: lo.lo_text for lo in ensure_goso_learning_outcomes(version, db)}
    courses = [_upsert_course(db, *definition) for definition in definitions]
    for definition, course in zip(definitions, courses):
        lo_code = GOSO_COURSE_LO_CODES.get(definition[0])
        if lo_code and goso_los.get(lo_code):
            course.learning_outcomes = [goso_los[lo_code]]
    by_code = {course.course_id: course for course in courses}
    # These global catalogue rows are reused between projects. Rebuild their
    # regulatory edges for the current duration instead of retaining a stale
    # edge created by an earlier programme.
    for course in courses:
        course.prerequisites = [
            parent for parent in course.prerequisites
            if not str(parent.course_id or "").startswith("GOSO-KZ-")
        ]
    for child, parent in _applicable_goso_prerequisite_pairs(by_code):
        if parent not in child.prerequisites:
            child.prerequisites.append(parent)
    profile_final = by_code.get("GOSO-KZ-MASTER_PROJECT_FINAL")
    profile_research = by_code.get("GOSO-KZ-EIRM_PROFILE_60") or by_code.get("GOSO-KZ-EIRM_PROFILE_90")
    if (
        profile_final
        and profile_research
        and int(profile_research.recommended_semester or 1) < int(profile_final.recommended_semester or 1)
        and profile_research not in profile_final.prerequisites
    ):
        profile_final.prerequisites.append(profile_research)
    db.flush()
    return [{
        "course_id": course.id,
        "title": course.title,
        "domain": course.domain,
        "credits": int(course.credits),
        "recommended_semester": int(course.recommended_semester),
        "latest_semester": int(course.recommended_semester),
        "prerequisites": [parent.id for parent in course.prerequisites],
        "type": course.cycle_component,
        "regulatory_required": True,
        "selection_method": "kz_goso_2026",
    } for course in courses]


def merge_goso_items(items: List[Dict], version: ProjectVersion, db: Session) -> List[Dict]:
    required = ensure_goso_items(version, db)
    required_keys = {item["course_id"] for item in required}
    return [*required, *[item for item in items if item.get("course_id") not in required_keys]]


def evaluate_goso_compliance(schedule: Dict[int, List[Dict]], version: ProjectVersion) -> Dict:
    constraints = version.project.constraints_json or {}
    if str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() != "KZ":
        return {"applicable": False, "violations": [], "compliant": True}
    level = str(constraints.get("education_level") or "bachelor").lower()
    selected = [item for rows in schedule.values() for item in rows]
    codes = set()
    for item in selected:
        course = getattr(item, "course", None)
        if course and course.course_id:
            codes.add(course.course_id)
    # Schedules are dictionaries during generation, so stable IDs are carried
    # via the database-backed regulatory flag/type and titles are checked too.
    titles = {str(item.get("title") or "") for item in selected}
    definitions = _definitions_for_constraints(constraints)
    missing = [title for _code, title, *_rest in definitions if title not in titles]
    mandatory_credits = sum(int(item.get("credits") or 0) for item in selected if str(item.get("type") or "").startswith("goso_"))
    violations = [{"reason": "missing_goso_component", "title": title} for title in missing]
    if level == "bachelor" and mandatory_credits < 56:
        violations.append({"reason": "goso_ood_credits", "actual": mandatory_credits, "required": 56})
    if level == "master":
        research = sum(int(item.get("credits") or 0) for item in selected if item.get("type") == "goso_research")
        final = sum(int(item.get("credits") or 0) for item in selected if item.get("type") == "goso_final")
        track = str(constraints.get("master_track") or "scientific_pedagogical").lower()
        required_research = 24 if track == "scientific_pedagogical" else 18 if int(constraints.get("total_credits") or 0) >= 90 else 13
        if research < required_research:
            violations.append({"reason": "goso_master_research", "actual": research, "required": required_research})
        if final < 8:
            violations.append({"reason": "goso_master_final", "actual": final, "required": 8})
    if level in {"doctorate", "doctoral", "phd"}:
        research = sum(int(item.get("credits") or 0) for item in selected if item.get("type") == "goso_research")
        final = sum(int(item.get("credits") or 0) for item in selected if item.get("type") == "goso_final")
        if research < 123:
            violations.append({"reason": "goso_doctoral_research", "actual": research, "required": 123})
        if final < 12:
            violations.append({"reason": "goso_doctoral_final", "actual": final, "required": 12})
    return {
        "applicable": bool(definitions),
        "jurisdiction": "KZ",
        "education_level": level,
        "compliant": not violations,
        "mandatory_credits": mandatory_credits,
        "violations": violations,
        "source": "ГОСО РК, редакция документа от 04.05.2026",
    }
