"""Export a compact, reproducible EPVO programme dataset for ML experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "backend" / "curriculum_kag.db"


def key(value, fallback: str) -> str:
    return str(value if value not in (None, "") else fallback)


def lo_key(value: object, fallback: str) -> str:
    if isinstance(value, dict):
        return key(value.get("id") or value.get("code"), fallback)
    return key(value, fallback)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(DEFAULT_DB))
    parser.add_argument("--output", default="experiment-results/epvo-ml/programs.jsonl")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.database)
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    query = "SELECT source_id,payload_json,collected_at FROM raw_epvo_programs ORDER BY id"
    if args.limit:
        query += f" LIMIT {int(args.limit)}"

    programmes = courses_total = links_total = skipped = 0
    with output.open("w", encoding="utf-8") as stream:
        for source_id, payload_json, collected_at in db.execute(query):
            payload = json.loads(payload_json)
            raw_courses = payload.get("disciplinesInfo") or []
            raw_los = payload.get("formedLearningOutcomes") or []
            if not raw_courses or not raw_los:
                skipped += 1
                continue

            courses, seen = [], set()
            for index, course in enumerate(raw_courses, 1):
                code = key(course.get("id") or course.get("subjectid"), f"{source_id}-C{index}")
                if code in seen:
                    continue
                seen.add(code)
                year = max(1, int(course.get("year") or 1))
                term = max(1, min(2, int(course.get("term") or 1)))
                semester = (year - 1) * 2 + term
                credits = max(1, int(round(float(course.get("creditscount") or 1))))
                linked_los = sorted({
                    lo_key(item, f"LO-{position}")
                    for position, item in enumerate(course.get("learningOutcomes") or [], 1)
                })
                courses.append({
                    "code": code,
                    "title": course.get("nameRu") or course.get("nameKz") or course.get("nameEn") or code,
                    "title_ru": course.get("nameRu"),
                    "title_kk": course.get("nameKz"),
                    "title_en": course.get("nameEn"),
                    "description_ru": course.get("briefinforu"),
                    "description_kk": course.get("briefinfo"),
                    "description_en": course.get("briefinfoen"),
                    "semester": semester,
                    "credits": credits,
                    "learning_outcomes": linked_los,
                })
                links_total += len(linked_los)

            if not courses:
                skipped += 1
                continue
            programme_los = [
                {
                    "code": lo_key(item, f"LO-{index}"),
                    "text": item.get("learningOutcomeNameRu") or item.get("nameRu") or item.get("descriptionRu") or item.get("learningOutcomeNameKz") or item.get("nameKz") or item.get("learningOutcomeNameEn") or item.get("nameEn") or "",
                }
                for index, item in enumerate(raw_los, 1)
            ]
            record = {
                "program_id": str(source_id),
                "university_id": key(payload.get("universityId"), "unknown"),
                "direction_id": key(payload.get("trainingDirectionsId"), "unknown"),
                "group_id": key(payload.get("groupEduProgram"), "unknown"),
                "courses": courses,
                "prerequisite_edges": [],
                "program_learning_outcomes": programme_los,
                "source": "EPVO public education programme registry snapshot",
                "snapshot_date": str(collected_at or date.today().isoformat())[:10],
                "license_or_permission": "local research use; portal terms must be confirmed before redistribution",
            }
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            programmes += 1
            courses_total += len(courses)

    db.close()
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest = {
        "output": str(output.resolve()),
        "sha256": digest,
        "programmes": programmes,
        "courses": courses_total,
        "declared_course_lo_links": links_total,
        "skipped_without_courses_or_los": skipped,
        "limit": args.limit or None,
        "prerequisite_edges": 0,
        "recommended_task": "bipartite course-LO link prediction",
        "redistribution_status": "terms_review_required",
    }
    output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
