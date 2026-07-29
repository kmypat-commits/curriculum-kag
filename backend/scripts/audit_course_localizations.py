"""Audit RU/KK/EN course localizations in SQLite or PostgreSQL."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE = f"sqlite:///{(ROOT / 'backend' / 'curriculum_kag.db').as_posix()}"
DEFAULT_OUT = (
    ROOT / "backend" / "experiment-results"
    / "translation-audit" / "course_localization_gaps.json"
)


def safe_database_name(url: str) -> str:
    if "@" not in url:
        return url
    prefix, suffix = url.rsplit("@", 1)
    scheme_user = prefix.split(":", 2)[:2]
    return ":".join(scheme_user) + ":***@" + suffix


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL") or DEFAULT_SQLITE,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    engine = create_engine(args.database_url, pool_pre_ping=True)
    missing: dict[str, int] = {}
    samples: dict[str, list[dict]] = {}
    with engine.connect() as connection:
        total_courses = int(connection.execute(text("SELECT count(*) FROM courses")).scalar() or 0)
        by_language = {
            str(row.language): int(row.count)
            for row in connection.execute(text(
                "SELECT language, count(*) AS count "
                "FROM course_localizations GROUP BY language"
            )).mappings()
        }
        for language in ("ru", "kk", "en"):
            condition = (
                "FROM courses c LEFT JOIN course_localizations l "
                "ON l.course_id = c.id AND l.language = :language "
                "WHERE l.id IS NULL"
            )
            missing[language] = int(connection.execute(
                text("SELECT count(*) " + condition),
                {"language": language},
            ).scalar() or 0)
            rows = connection.execute(
                text(
                    "SELECT c.id, c.course_id, c.title "
                    + condition + " ORDER BY c.id LIMIT 30"
                ),
                {"language": language},
            ).mappings()
            samples[language] = [dict(row) for row in rows]

    report = {
        "database": safe_database_name(args.database_url),
        "database_dialect": engine.dialect.name,
        "total_courses": total_courses,
        "localized_by_language": by_language,
        "missing_by_language": missing,
        "complete": total_courses > 0 and all(value == 0 for value in missing.values()),
        "samples": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "complete": report["complete"],
        "database": report["database_dialect"],
        "courses": total_courses,
        "localized": by_language,
        "missing": missing,
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
