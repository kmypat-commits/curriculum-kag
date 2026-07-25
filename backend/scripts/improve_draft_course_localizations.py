"""Improve draft course localizations with deterministic RU/KK/EN labels.

This script deliberately keeps status='draft': the values are clearer for UI,
but they are not expert-verified EPVO translations.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "curriculum_kag.db"


AI = {
    "Основы цифровой криминалистики": {
        "kk": "Цифрлық криминалистика негіздері",
        "en": "Fundamentals of Digital Forensics",
        "desc_kk": "Курс цифрлық дәлелдерді жинау, талдау және сақтау әдістерін қарастырады. Студенттер киберинциденттерді тергеу қағидаларын және дәлелдемелер тізбегін құжаттауды үйренеді.",
        "desc_en": "The course covers methods and tools for collecting, analysing and preserving digital evidence. Students study basic cyber incident investigation principles and evidence chain documentation.",
    },
    "Цифровая криминалистика": {
        "kk": "Цифрлық криминалистика",
        "en": "Digital Forensics",
        "desc_kk": "Пән цифрлық дәлелдерді жинау, талдау және сақтау құралдарын зерттейді. Файлдық жүйелер, оқиғалар журналдары және жүйелік артефактілер қарастырылады.",
        "desc_en": "The course studies methods and tools for collecting, analysing and preserving digital evidence, including file systems, event logs and system artefacts.",
    },
    "Расследование киберпреступлений в социальных сетях": {
        "kk": "Әлеуметтік желілердегі киберқылмыстарды тергеу",
        "en": "Investigation of Cybercrimes in Social Networks",
        "desc_kk": "Пән әлеуметтік желілермен байланысты киберқылмыстарды тергеу әдістерін, деректерді талдау, дәлелдемелер жинау және құқықтық аспектілерді қамтиды.",
        "desc_en": "The course focuses on investigating cybercrimes related to social networks, including data analysis, evidence collection and legal aspects.",
    },
    "Этика и правовые аспекты искусственного интеллекта": {
        "kk": "Жасанды интеллектінің этикалық және құқықтық аспектілері",
        "en": "Ethical and Legal Aspects of Artificial Intelligence",
        "desc_kk": "Пән жасанды интеллект саласындағы құқықтық және этикалық стандарттарды, кемсітушілік пен біржақтылық жағдайларын және оларды азайту тәсілдерін қарастырады.",
        "desc_en": "The course studies legal and ethical standards in artificial intelligence, including bias, discrimination and mitigation recommendations.",
    },
}


EPVO_EN_TITLES = {
    "Профессионально-прикладные программы специальности": "Professional Applied Programmes of the Specialty",
    "Методика проведения экономических исследований": "Methods of Conducting Economic Research",
    "Человеческий капитал в условиях экономики знаний": "Human Capital in the Knowledge Economy",
    "Управление в макроэкономической среде": "Management in the Macroeconomic Environment",
    "Анализ проблемных ситуаций и методы принятия управленческих решений": "Analysis of Problem Situations and Management Decision-Making Methods",
    "Экономика инвестиций": "Investment Economics",
    "Практикум по решению лингвистических задач": "Practicum in Solving Linguistic Problems",
    "Компьютерные сети и аудит сетевой безопасности": "Computer Networks and Network Security Audit",
    "Основы компьютерной алгебры": "Fundamentals of Computer Algebra",
    "Стандарты и политики информационной безопасности": "Information Security Standards and Policies",
    "Защита программ и данных": "Software and Data Protection",
    "Инструментальные средства обработки больших данных": "Big Data Processing Tools",
    "Моделирование и визуализация в системах больших данных": "Modelling and Visualisation in Big Data Systems",
    "Информационная безопасность и технология защиты информации": "Information Security and Information Protection Technology",
    "Гармонический анализ": "Harmonic Analysis",
    "Дискретные и вероятностные модели вычислений": "Discrete and Probabilistic Models of Computation",
    "Комбинаторно-алгебраические модели в криптографии": "Combinatorial and Algebraic Models in Cryptography",
    "Анализ и проектирование алгоритмов (теория алгоритмов)": "Analysis and Design of Algorithms (Theory of Algorithms)",
    "Римское право / История политических и правовых учений": "Roman Law / History of Political and Legal Doctrines",
}


GOSO_TITLES = {
    "HISTORY_KZ": ("Қазақстан тарихы", "History of Kazakhstan"),
    "PHILOSOPHY": ("Философия", "Philosophy"),
    "KZ_RU_1": ("Қазақ (орыс) тілі 1", "Kazakh (Russian) Language 1"),
    "KZ_RU_2": ("Қазақ (орыс) тілі 2", "Kazakh (Russian) Language 2"),
    "FOREIGN_1": ("Шетел тілі 1", "Foreign Language 1"),
    "FOREIGN_2": ("Шетел тілі 2", "Foreign Language 2"),
    "ICT": ("Ақпараттық-коммуникациялық технологиялар", "Information and Communication Technologies"),
    "SOCIAL_POLITICAL": ("Әлеуметтік-саяси білім модулі", "Module of Social and Political Knowledge"),
    "PHYSICAL_1": ("Дене шынықтыру 1", "Physical Education 1"),
    "PHYSICAL_2": ("Дене шынықтыру 2", "Physical Education 2"),
    "OOD_UNIVERSITY": ("Құқық негіздері және академиялық адалдық", "Fundamentals of Law and Academic Integrity"),
    "BACHELOR_FINAL_ATTESTATION": ("Дипломдық жұмысты (жобаны) жазу және қорғау немесе кешенді емтихан", "Writing and Defending a Diploma Thesis (Project) or Comprehensive Examination"),
    "HISTORY_PHIL_SCIENCE": ("Ғылым тарихы және философиясы", "History and Philosophy of Science"),
    "PROF_FOREIGN": ("Кәсіби шетел тілі", "Professional Foreign Language"),
    "HIGHER_PEDAGOGY": ("Жоғары мектеп педагогикасы", "Higher Education Pedagogy"),
    "MANAGEMENT_PSYCHOLOGY": ("Басқару психологиясы", "Management Psychology"),
    "PEDAGOGICAL_PRACTICE": ("Педагогикалық практика", "Pedagogical Practice"),
    "RESEARCH_PRACTICE": ("Зерттеу практикасы", "Research Practice"),
    "FINAL_ATTESTATION": ("Магистрлік диссертацияны ресімдеу және қорғау", "Preparation and Defence of the Master's Thesis"),
    "MASTER_PRODUCTION_PRACTICE": ("Магистранттың өндірістік практикасы", "Master's Student Production Practice"),
    "MASTER_PROJECT_FINAL": ("Магистрлік жобаны ресімдеу және қорғау", "Preparation and Defence of the Master's Project"),
    "DOCTORAL_PEDAGOGICAL_PRACTICE": ("Докторанттың педагогикалық практикасы", "Doctoral Pedagogical Practice"),
    "DOCTORAL_RESEARCH_PRACTICE": ("Докторанттың зерттеу практикасы", "Doctoral Research Practice"),
    "DOCTORAL_PRODUCTION_PRACTICE": ("Докторанттың өндірістік практикасы", "Doctoral Production Practice"),
    "DOCTORAL_FINAL_ATTESTATION": ("Докторлық диссертацияны жазу және қорғау", "Writing and Defending a Doctoral Dissertation"),
}


def goso_title(code: str, ru_title: str) -> tuple[str, str]:
    key = code.removeprefix("GOSO-KZ-")
    if key in GOSO_TITLES:
        return GOSO_TITLES[key]
    match = re.match(r"(NIRM|NIRD|EIRD)_(\d+)", key)
    if match:
        kind, number = match.groups()
        if kind == "NIRM":
            return (f"Магистранттың ғылыми-зерттеу жұмысы {number}", f"Master's Research Work {number}")
        if kind == "NIRD":
            return (f"Докторанттың ғылыми-зерттеу жұмысы {number}", f"Doctoral Research Work {number}")
        return (f"Докторанттың эксперименттік-зерттеу жұмысы {number}", f"Doctoral Experimental Research Work {number}")
    if key.startswith("EIRM_PROFILE"):
        return ("Магистранттың эксперименттік-зерттеу жұмысы, тағылымдама және магистрлік жоба", "Master's Experimental Research Work, Internship and Master's Project")
    return (ru_title, ru_title)


def goso_desc(code: str, ru_desc: str) -> tuple[str, str]:
    return (
        f"ҚР МЖМБС бойынша міндетті компонент. {ru_desc}",
        f"Mandatory component under the Kazakhstan State Compulsory Education Standard. {ru_desc}",
    )


def bridge_values(title: str, description: str) -> dict:
    tail = title.split(":", 1)[-1].strip()
    ru = f"Междисциплинарная интеграция: {tail}"
    kk = f"Пәнаралық интеграция: {tail}"
    en = f"Interdisciplinary Integration: {tail}"
    lo_match = re.search(r"Targets LOs:\s*(.+)", description or "")
    los = lo_match.group(1) if lo_match else "целевые результаты обучения"
    return {
        "ru": (ru, f"Bridge-модуль связывает выбранные области программы и усиливает покрытие результатов обучения: {los}."),
        "kk": (kk, f"Bridge-модуль бағдарламаның таңдалған бағыттарын байланыстырып, оқу нәтижелерін қамтуды күшейтеді: {los}."),
        "en": (en, f"The bridge module connects the selected programme domains and strengthens learning outcome coverage: {los}."),
    }


def main() -> None:
    updated = 0
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """
            SELECT c.id, c.course_id, c.title, c.description
            FROM courses c
            WHERE EXISTS (
                SELECT 1 FROM course_localizations l
                WHERE l.course_id=c.id AND l.status='draft'
            )
            """
        ).fetchall()
        for course in rows:
            code = course["course_id"] or ""
            title = course["title"] or ""
            description = course["description"] or ""
            values = None
            if code.startswith("GOSO-KZ-"):
                kk_title, en_title = goso_title(code, title)
                kk_desc, en_desc = goso_desc(code, description)
                values = {"ru": (title, description), "kk": (kk_title, kk_desc), "en": (en_title, en_desc)}
            elif code.startswith("AI-CONFIRMED-") and title in AI:
                row = AI[title]
                values = {"ru": (title, description), "kk": (row["kk"], row["desc_kk"]), "en": (row["en"], row["desc_en"])}
            elif code.startswith("BRIDGE_"):
                values = bridge_values(title, description)
            elif code.startswith("EPVO-") and title in EPVO_EN_TITLES:
                values = {"en": (EPVO_EN_TITLES[title], description)}
            if not values:
                continue
            for language, (next_title, next_description) in values.items():
                cursor = db.execute(
                    """
                    UPDATE course_localizations
                    SET title=?, description=?, source='rule_based_draft', updated_at=CURRENT_TIMESTAMP
                    WHERE course_id=? AND language=? AND status='draft'
                    """,
                    (next_title, next_description, course["id"], language),
                )
                updated += cursor.rowcount
        db.commit()
    print(json.dumps({"status": "complete", "draft_rows_updated": updated}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
