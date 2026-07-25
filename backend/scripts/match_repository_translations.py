"""Recover verified translations by high-confidence fuzzy matching to EPVO."""
import json
import re
import sqlite3
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "curriculum_kag.db"
OUTPUT = ROOT / "backend" / "data" / "course_translations.json"
STOP = {"and", "of", "the", "in", "for", "и", "в", "на", "по", "для", "мен", "және"}


def normalized(value):
    return " ".join(re.findall(r"[0-9a-zа-яәіңғүұқөһ+#.]+", str(value or "").lower()))


def tokens(value):
    return {token for token in normalized(value).split() if len(token) > 1 and token not in STOP}


def score(left, right):
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    jaccard = len(a & b) / len(a | b)
    sequence = SequenceMatcher(None, normalized(left), normalized(right)).ratio()
    containment = len(a & b) / min(len(a), len(b))
    return 0.45 * jaccard + 0.35 * sequence + 0.20 * containment


def append_suffix(source, target):
    match = re.search(r"\s([1-9])$", str(source))
    if match and not re.search(rf"\s{match.group(1)}$", str(target or "")):
        return f"{target} {match.group(1)}"
    return target


def main():
    db = sqlite3.connect(DB)
    courses = db.execute("SELECT id,title,language FROM courses ORDER BY id").fetchall()
    epvo = db.execute("SELECT id,title_ru,title_kk,title_en FROM epvo_disciplines_normalized WHERE title_ru IS NOT NULL OR title_kk IS NOT NULL OR title_en IS NOT NULL").fetchall()
    data = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    indexes = {"ru": defaultdict(set), "kk": defaultdict(set), "en": defaultdict(set)}
    for index, row in enumerate(epvo):
        for language, position in (("ru", 1), ("kk", 2), ("en", 3)):
            for token in tokens(row[position]):
                indexes[language][token].add(index)
    matched, ambiguous = 0, 0
    for course_id, title, language in courses:
        current = data.get(str(course_id), {})
        if current.get("review_status") == "verified_epvo":
            continue
        language = "kk" if language in {"kk", "kz"} else language
        position = {"ru": 1, "kk": 2, "en": 3}.get(language, 1)
        candidates = set()
        for token in tokens(title):
            candidates.update(indexes[language].get(token, ()))
        ranked = sorted(((score(title, epvo[index][position]), index) for index in candidates), reverse=True)[:2]
        if not ranked or ranked[0][0] < 0.91 or (len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.025):
            ambiguous += 1
            continue
        confidence, index = ranked[0]
        row = epvo[index]
        data[str(course_id)] = {
            "review_status": "verified_epvo_fuzzy", "source_language": language,
            "source": {"dataset": "epvo_normalized", "normalized_discipline_id": row[0], "match_confidence": round(confidence, 4)},
            "title": {"ru": append_suffix(title, row[1]), "kk": append_suffix(title, row[2]), "en": append_suffix(title, row[3])},
        }
        matched += 1
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"repository_courses": len(courses), "fuzzy_verified": matched, "remaining": ambiguous}, ensure_ascii=False))


if __name__ == "__main__":
    main()
