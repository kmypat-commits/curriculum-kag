"""Audit missing course localizations after SQLite translation migration."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "curriculum_kag.db"
OUT = ROOT / "backend" / "experiment-results" / "translation-audit" / "course_localization_gaps.json"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        total_courses = db.execute("SELECT count(*) FROM courses").fetchone()[0]
        by_language = {
            row["language"]: row["count"]
            for row in db.execute(
                "SELECT language, count(*) AS count FROM course_localizations GROUP BY language"
            )
        }
        missing = {}
        samples = {}
        for language in ("ru", "kk", "en"):
            rows = db.execute(
                """
                SELECT c.id, c.course_id, c.title
                FROM courses c
                LEFT JOIN course_localizations l
                    ON l.course_id = c.id AND l.language = ?
                WHERE l.id IS NULL
                ORDER BY c.id
                LIMIT 30
                """,
                (language,),
            ).fetchall()
            count = db.execute(
                """
                SELECT count(*)
                FROM courses c
                LEFT JOIN course_localizations l
                    ON l.course_id = c.id AND l.language = ?
                WHERE l.id IS NULL
                """,
                (language,),
            ).fetchone()[0]
            missing[language] = count
            samples[language] = [dict(row) for row in rows]
        report = {
            "database": str(DB),
            "total_courses": total_courses,
            "localized_by_language": by_language,
            "missing_by_language": missing,
            "samples": samples,
        }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
