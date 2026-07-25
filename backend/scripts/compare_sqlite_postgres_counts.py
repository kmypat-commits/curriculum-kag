"""Compare key SQLite and PostgreSQL table counts after migration.

This is a safe post-migration smoke check: it does not mutate either database.
It uses sqlite3 from the standard library and SQLAlchemy for PostgreSQL.
If the PostgreSQL driver is not installed, the script exits with a clear message.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


DEFAULT_TABLES = [
    "users",
    "projects",
    "project_versions",
    "learning_outcomes",
    "courses",
    "course_localizations",
    "plans",
    "plan_items",
    "raw_epvo_programs",
    "raw_epvo_disciplines",
    "raw_epvo_learning_outcomes",
    "raw_epvo_expert_checks",
    "epvo_directions",
    "epvo_groups",
    "epvo_disciplines_normalized",
    "epvo_discipline_lo_links",
    "epvo_prerequisites",
    "embeddings",
    "match_scores",
]


def sqlite_count(db_path: Path, table: str) -> int | None:
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as db:
        try:
            return int(db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        except sqlite3.Error:
            return None


def sqlite_valid_count(db_path: Path, table: str) -> int | None:
    valid_sql = {
        "embeddings": (
            "SELECT COUNT(*) FROM embeddings e "
            "JOIN course_chunks c ON e.chunk_id = c.id"
        ),
        "match_scores": (
            "SELECT COUNT(*) FROM match_scores m "
            "JOIN project_versions v ON m.project_version_id = v.id "
            "LEFT JOIN courses c ON m.course_id = c.id "
            "LEFT JOIN learning_outcomes lo ON m.lo_id = lo.id "
            "LEFT JOIN course_chunks ch ON m.chunk_id = ch.id "
            "WHERE (m.course_id IS NULL OR c.id IS NOT NULL) "
            "AND (m.lo_id IS NULL OR lo.id IS NOT NULL) "
            "AND (m.chunk_id IS NULL OR ch.id IS NOT NULL)"
        ),
        "match_feedback": (
            "SELECT COUNT(*) FROM match_feedback mf "
            "JOIN project_versions v ON mf.project_version_id = v.id "
            "JOIN courses c ON mf.course_id = c.id "
            "JOIN learning_outcomes lo ON mf.lo_id = lo.id"
        ),
        "bridge_modules": (
            "SELECT COUNT(*) FROM bridge_modules b "
            "JOIN project_versions v ON b.project_version_id = v.id "
            "LEFT JOIN users u ON b.created_by = u.id "
            "WHERE b.created_by IS NULL OR u.id IS NOT NULL"
        ),
    }
    sql = valid_sql.get(table)
    if not sql:
        return sqlite_count(db_path, table)
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as db:
        try:
            return int(db.execute(sql).fetchone()[0])
        except sqlite3.Error:
            return None


def postgres_engine(url: str):
    try:
        from sqlalchemy import create_engine, text
    except Exception as exc:  # pragma: no cover - depends on local env
        raise RuntimeError(
            "Не найден SQLAlchemy/драйвер PostgreSQL. Запустите из backend-venv "
            "или установите зависимости backend перед сравнением."
        ) from exc
    return create_engine(url), text


def postgres_count(pg_url: str, table: str) -> int | None:
    engine, text = postgres_engine(pg_url)
    with engine.connect() as conn:
        exists = conn.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :table)"
            ),
            {"table": table},
        ).scalar()
        if not exists:
            return None
        return int(conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path, default=Path("backend/curriculum_kag.db"))
    parser.add_argument("--postgres", required=True, help="postgresql+psycopg2://...")
    parser.add_argument("--tables", nargs="*", default=DEFAULT_TABLES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = []
    passed = True
    for table in args.tables:
        sqlite_rows = sqlite_count(args.sqlite, table)
        try:
            postgres_rows = postgres_count(args.postgres, table)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        sqlite_valid_rows = sqlite_valid_count(args.sqlite, table)
        row_passed = sqlite_rows == postgres_rows or sqlite_valid_rows == postgres_rows
        passed = passed and row_passed
        rows.append(
            {
                "table": table,
                "sqlite": sqlite_rows,
                "sqlite_valid": sqlite_valid_rows,
                "postgres": postgres_rows,
                "skipped_orphan_rows": (
                    sqlite_rows - sqlite_valid_rows
                    if isinstance(sqlite_rows, int) and isinstance(sqlite_valid_rows, int)
                    else None
                ),
                "passed": row_passed,
            }
        )

    report = {"passed": passed, "tables": rows}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
