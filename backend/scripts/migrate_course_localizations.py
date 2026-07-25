"""Create and populate course_localizations from EPVO and legacy JSON translations."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "curriculum_kag.db"
TRANSLATIONS = ROOT / "backend" / "data" / "course_translations.json"


def backup_database(source: Path) -> Path:
    output_dir = ROOT / "backups" / "translation-migration"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"curriculum_kag_before_course_localizations_{datetime.now():%Y-%m-%d_%H-%M-%S}.db"
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    with sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True) as db:
        check = db.execute("PRAGMA quick_check").fetchone()[0]
    if check != "ok":
        raise RuntimeError(f"Backup quick_check failed: {check}")
    return target


def create_table(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS course_localizations (
            id INTEGER PRIMARY KEY,
            course_id INTEGER NOT NULL,
            language TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            source TEXT NOT NULL DEFAULT 'manual',
            status TEXT NOT NULL DEFAULT 'draft',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_id, language),
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS ix_course_localizations_course_id ON course_localizations(course_id)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_course_localizations_language ON course_localizations(language)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_course_localizations_source ON course_localizations(source)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_course_localizations_status ON course_localizations(status)")


def upsert(db: sqlite3.Connection, course_id: int, language: str, title: str, description: str | None, source: str, status: str) -> bool:
    title = (title or "").strip()
    if not title:
        return False
    current = db.execute(
        "SELECT status FROM course_localizations WHERE course_id=? AND language=?",
        (course_id, language),
    ).fetchone()
    if current and current["status"] == "verified" and status != "verified":
        return False
    db.execute(
        """
        INSERT INTO course_localizations(course_id, language, title, description, source, status, updated_at)
        VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(course_id, language) DO UPDATE SET
            title=excluded.title,
            description=coalesce(excluded.description, course_localizations.description),
            source=excluded.source,
            status=excluded.status,
            updated_at=CURRENT_TIMESTAMP
        """,
        (course_id, language, title, description, source, status),
    )
    return True


def import_legacy_json(db: sqlite3.Connection) -> int:
    if not TRANSLATIONS.exists():
        return 0
    records = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
    inserted = 0
    for key, payload in records.items():
        course = db.execute("SELECT id FROM courses WHERE id=? OR course_id=?", (key, str(key))).fetchone()
        if not course:
            continue
        titles = payload.get("title") if isinstance(payload.get("title"), dict) else {}
        descriptions = payload.get("description") if isinstance(payload.get("description"), dict) else {}
        raw_status = payload.get("review_status") or "draft"
        status = "verified" if raw_status in {"approved", "verified_epvo", "verified_epvo_fuzzy", "machine_reviewed"} else "draft"
        source_value = payload.get("source") or "legacy_json"
        source = source_value if isinstance(source_value, str) else "legacy_json"
        for language in ("ru", "kk", "en"):
            if upsert(db, course["id"], language, titles.get(language), descriptions.get(language), source, status):
                inserted += 1
    return inserted


def import_epvo(db: sqlite3.Connection) -> int:
    rows = db.execute(
        """
        SELECT c.id AS course_id, e.title_ru, e.title_kk, e.title_en, e.content_json
        FROM courses c
        JOIN epvo_disciplines_normalized e ON c.course_id = 'EPVO-' || e.id
        """
    ).fetchall()
    inserted = 0
    for row in rows:
        try:
            content = json.loads(row["content_json"]) if isinstance(row["content_json"], str) else (row["content_json"] or {})
        except Exception:
            content = {}
        descriptions = {
            "ru": content.get("description_ru"),
            "kk": content.get("description_kk"),
            "en": content.get("description_en"),
        }
        titles = {"ru": row["title_ru"], "kk": row["title_kk"], "en": row["title_en"]}
        for language in ("ru", "kk", "en"):
            if upsert(db, row["course_id"], language, titles.get(language), descriptions.get(language), "epvo", "verified"):
                inserted += 1
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(DB))
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    database = Path(args.database)
    backup = None if args.no_backup else backup_database(database)
    with sqlite3.connect(database, timeout=120) as db:
        db.row_factory = sqlite3.Row
        create_table(db)
        epvo_count = import_epvo(db)
        legacy_count = import_legacy_json(db)
        db.commit()
        total = db.execute("SELECT count(*) FROM course_localizations").fetchone()[0]
    print(json.dumps({
        "status": "complete",
        "database": str(database),
        "backup": str(backup) if backup else None,
        "epvo_upserts": epvo_count,
        "legacy_upserts": legacy_count,
        "course_localizations_total": total,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
