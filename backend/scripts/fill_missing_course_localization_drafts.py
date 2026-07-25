"""Fill missing localization rows with draft fallbacks, preserving verified data."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "curriculum_kag.db"


def main() -> None:
    inserted = 0
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        courses = db.execute("SELECT id, title, description FROM courses").fetchall()
        for course in courses:
            for language in ("ru", "kk", "en"):
                exists = db.execute(
                    "SELECT 1 FROM course_localizations WHERE course_id=? AND language=?",
                    (course["id"], language),
                ).fetchone()
                if exists:
                    continue
                db.execute(
                    """
                    INSERT INTO course_localizations(course_id, language, title, description, source, status)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (
                        course["id"],
                        language,
                        course["title"],
                        course["description"],
                        "fallback_from_course",
                        "draft",
                    ),
                )
                inserted += 1
        db.commit()
        total = db.execute("SELECT count(*) FROM course_localizations").fetchone()[0]
        by_language = dict(db.execute("SELECT language, count(*) FROM course_localizations GROUP BY language").fetchall())
        by_status = dict(db.execute("SELECT status, count(*) FROM course_localizations GROUP BY status").fetchall())
    print(json.dumps({
        "status": "complete",
        "inserted": inserted,
        "total": total,
        "by_language": by_language,
        "by_status": by_status,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
