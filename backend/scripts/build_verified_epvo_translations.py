"""Match active repository courses to expert RU/KK/EN EPVO cards."""
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "curriculum_kag.db"
SOURCE = ROOT / "backend" / "experiment-results" / "epvo-expert-labels" / "course_lo_pairs.jsonl"
OUTPUT = ROOT / "backend" / "data" / "course_translations.json"


def normalize(value):
    return re.sub(r"[^0-9a-zа-яәіңғүұқөһ]+", " ", str(value).lower()).strip()


def main():
    with sqlite3.connect(DB) as db:
        courses = db.execute("SELECT id, course_id, title, language FROM courses ORDER BY id").fetchall()
    by_title = defaultdict(list)
    for course in courses:
        by_title[normalize(course[2])].append(course)
    candidates = defaultdict(Counter)
    payloads = {}
    with SOURCE.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            titles = row.get("course_title") or {}
            matched_ids = set()
            for title in titles.values():
                for course in by_title.get(normalize(title), []):
                    matched_ids.add(course[0])
            if not matched_ids:
                continue
            signature = tuple(str(titles.get(lang) or "") for lang in ("ru", "kz", "en"))
            for course_id in matched_ids:
                candidates[course_id][signature] += 1
                payloads[(course_id, signature)] = row
    data = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    for course_id, options in candidates.items():
        signature, frequency = options.most_common(1)[0]
        row = payloads[(course_id, signature)]
        titles = row.get("course_title") or {}
        descriptions = row.get("course_description") or {}
        data[str(course_id)] = {
            "review_status": "verified_epvo",
            "source_language": next((lang for lang in ("ru", "kz", "en") if titles.get(lang)), "ru"),
            "source": {"dataset": "epvo_expert_labels", "program_id": row.get("program_id"), "course_id": row.get("course_id"), "occurrences": frequency},
            "title": {"ru": titles.get("ru"), "kk": titles.get("kz"), "en": titles.get("en")},
            "description": {"ru": descriptions.get("ru"), "kk": descriptions.get("kz"), "en": descriptions.get("en")},
        }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"repository_courses": len(courses), "verified_epvo": len(candidates), "unmatched": len(courses) - len(candidates)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
