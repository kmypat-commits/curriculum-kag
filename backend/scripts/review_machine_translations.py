"""Apply a terminology glossary and promote only QA-passing title drafts."""
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "backend" / "data" / "course_translations.json"
CORRECTIONS = {
    "Algorithms and Data Structures 1": {"ru": "Алгоритмы и структуры данных 1", "kk": "Алгоритмдер және деректер құрылымдары 1", "en": "Algorithms and Data Structures 1"},
    "Algorithms and Data Structures 2": {"ru": "Алгоритмы и структуры данных 2", "kk": "Алгоритмдер және деректер құрылымдары 2", "en": "Algorithms and Data Structures 2"},
    "Rust Programming": {"ru": "Программирование на Rust", "kk": "Rust тілінде бағдарламалау", "en": "Rust Programming"},
    "Web Development (Frontend)": {"ru": "Веб-разработка (Frontend)", "kk": "Веб-әзірлеу (Frontend)", "en": "Web Development (Frontend)"},
    "Web Development (Backend)": {"ru": "Веб-разработка (Backend)", "kk": "Веб-әзірлеу (Backend)", "en": "Web Development (Backend)"},
    "DBMS Administration": {"ru": "Администрирование СУБД", "kk": "ДҚБЖ әкімшілендіру", "en": "DBMS Administration"},
    "Graph Databases": {"ru": "Графовые базы данных", "kk": "Графтық деректер базалары", "en": "Graph Databases"},
    "Data Warehouses": {"ru": "Хранилища данных", "kk": "Деректер қоймалары", "en": "Data Warehouses"},
    "Software-Defined Networking (SDN)": {"ru": "Программно-определяемые сети (SDN)", "kk": "Бағдарламалық-анықталатын желілер (SDN)", "en": "Software-Defined Networking (SDN)"},
    "Requirements Engineering": {"ru": "Инженерия требований", "kk": "Талаптар инженериясы", "en": "Requirements Engineering"},
    "Agile Methodologies": {"ru": "Гибкие методологии (Agile)", "kk": "Agile әдіснамалары", "en": "Agile Methodologies"},
    "Internet of Things (IoT) Networks": {"ru": "Сети Интернета вещей (IoT)", "kk": "Заттар интернеті (IoT) желілері", "en": "Internet of Things (IoT) Networks"},
    "Advanced Circuit Analysis": {"ru": "Углублённый анализ электрических цепей", "kk": "Электр тізбектерін тереңдетілген талдау", "en": "Advanced Circuit Analysis"},
    ".NET Platform and C#": {"ru": "Платформа .NET и C#", "kk": ".NET платформасы және C#", "en": ".NET Platform and C#"},
    "ORM and Data Access": {"ru": "ORM и доступ к данным", "kk": "ORM және деректерге қол жеткізу", "en": "ORM and Data Access"},
    "Containerization": {"ru": "Контейнеризация", "kk": "Контейнерлеу", "en": "Containerization"},
    "CI/CD Practices": {"ru": "Практики CI/CD", "kk": "CI/CD тәжірибелері", "en": "CI/CD Practices"},
    "Quality Assurance (QA)": {"ru": "Обеспечение качества (QA)", "kk": "Сапаны қамтамасыз ету (QA)", "en": "Quality Assurance (QA)"},
    "Speech Recognition": {"ru": "Распознавание речи", "kk": "Сөйлеуді тану", "en": "Speech Recognition"},
    "AI Ethics": {"ru": "Этика искусственного интеллекта", "kk": "Жасанды интеллект этикасы", "en": "AI Ethics"},
    "Collection and Preservation of Digital Evidence": {"ru": "Сбор и сохранение цифровых доказательств", "kk": "Цифрлық дәлелдемелерді жинау және сақтау", "en": "Collection and Preservation of Digital Evidence"},
    "Procedural Requirements in IT": {"ru": "Процессуальные требования в ИТ", "kk": "IT саласындағы процестік талаптар", "en": "Procedural Requirements in IT"},
    "Digital Rights Management": {"ru": "Управление цифровыми правами", "kk": "Цифрлық құқықтарды басқару", "en": "Digital Rights Management"},
    "Linux Forensics": {"ru": "Цифровая криминалистика Linux", "kk": "Linux цифрлық криминалистикасы", "en": "Linux Forensics"},
    "Email Incident Investigation": {"ru": "Расследование инцидентов электронной почты", "kk": "Электрондық пошта инциденттерін тергеу", "en": "Email Incident Investigation"},
    "Distributed Architecture Forensics": {"ru": "Криминалистический анализ распределённых архитектур", "kk": "Таратылған архитектуралардың криминалистикалық талдауы", "en": "Distributed Architecture Forensics"},
    "IoT Forensics": {"ru": "Цифровая криминалистика IoT", "kk": "IoT цифрлық криминалистикасы", "en": "IoT Forensics"},
    "Exploit Development": {"ru": "Разработка эксплойтов", "kk": "Эксплойттарды әзірлеу", "en": "Exploit Development"},
    "Rootkit and Bootkit Analysis": {"ru": "Анализ руткитов и буткитов", "kk": "Rootkit және Bootkit талдауы", "en": "Rootkit and Bootkit Analysis"},
    "Python for Digital Forensics": {"ru": "Python для цифровой криминалистики", "kk": "Цифрлық криминалистикаға арналған Python", "en": "Python for Digital Forensics"},
}
PROTECTED = ("SQL", "DBMS", "ORM", "IoT", "SDN", "CI/CD", "QA", "AI", "IT", "C++", "C#", ".NET", "Linux", "Android", "macOS", "iOS", "NTFS", "FAT", "Ext4", "Btrfs", "APFS", "PCAP", "IDS", "IPS", "Rust")
FORBIDDEN = ("корроз", "склады данных", "графические базы", "требования инженерные", "анализ циклов", "қалғандық", "веб-дизайнды")


def valid(source, titles):
    if not all(str(titles.get(lang) or "").strip() for lang in ("ru", "kk", "en")):
        return False
    joined = " | ".join(titles.values()).lower()
    if any(value in joined for value in FORBIDDEN):
        return False
    for token in PROTECTED:
        if token.lower() in source.lower() and any(token.lower() not in str(titles[lang]).lower() for lang in ("ru", "kk", "en")):
            return False
    if not re.search(r"[А-Яа-я]", titles["ru"]) or not re.search(r"[А-Яа-яӘәІіҢңҒғҮүҰұҚқӨөҺһ]", titles["kk"]):
        return False
    lengths = [len(titles[lang]) for lang in ("ru", "kk", "en")]
    return max(lengths) / max(min(lengths), 1) < 3.2


def main():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    promoted = rejected = corrected = 0
    for record in data.values():
        if record.get("review_status") != "machine_draft":
            continue
        titles = record.get("title") or {}
        source = titles.get(record.get("source_language")) or titles.get("en") or titles.get("ru") or ""
        glossary_key = titles.get("en") if titles.get("en") in CORRECTIONS else source
        if glossary_key in CORRECTIONS:
            record["title"] = titles = CORRECTIONS[glossary_key]
            record["terminology_review"] = "curated_glossary"
            record["review_status"] = "machine_reviewed"
            corrected += 1
            promoted += 1
            continue
        if valid(source, titles):
            record["review_status"] = "machine_reviewed"
            record.setdefault("terminology_review", "automatic_qa")
            promoted += 1
        else:
            rejected += 1
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"machine_reviewed": promoted, "still_draft": rejected, "glossary_corrected": corrected}, ensure_ascii=False))


if __name__ == "__main__":
    main()
