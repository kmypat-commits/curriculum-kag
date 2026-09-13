"""Compare key SQLite and PostgreSQL table counts after migration.

This is a safe post-migration smoke check: it does not mutate either database.
It uses sqlite3 from the standard library and SQLAlchemy for PostgreSQL.
If the PostgreSQL driver is not installed, the script exits with a clear message.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

HASH_BATCH_SIZE = 5000
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


def _canonical(value):
    if isinstance(value, datetime):
        # sqlite commonly returns an ISO string while psycopg2 returns a
        # datetime object. Both representations must hash identically even
        # when one side has no explicit timezone.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        try:
            parsed_dt = datetime.fromisoformat(value.replace(" ", "T"))
            if parsed_dt.tzinfo is None:
                return parsed_dt.replace(tzinfo=timezone.utc).isoformat()
            return parsed_dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
        # Do not materialize large raw EPVO texts merely to normalize them.
        # PostgreSQL and SQLite already preserve these payloads byte-for-byte.
        if len(value) <= 8192:
            try:
                parsed = json.loads(value)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except (TypeError, json.JSONDecodeError):
                pass
    return value


def _digest_rows(rows) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps([_canonical(value) for value in row], ensure_ascii=False, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _update_digest(digest, rows) -> None:
    for row in rows:
        digest.update(json.dumps([_canonical(value) for value in row], ensure_ascii=False, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")


def _digest_rows_for_table(rows, table: str, columns: list[str]) -> str:
    """Digest derived vector rows after applying the migration's vector normalization."""
    vector_indexes = {index for index, column in enumerate(columns) if (table, column) in {("embeddings", "vector"), ("match_scores", "vector")}}
    if not vector_indexes:
        return _digest_rows(rows)
    digest = hashlib.sha256()
    for row in rows:
        normalized = []
        for index, value in enumerate(row):
            if index in vector_indexes and isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = [float(item) for item in value.strip("[]").split(",") if item.strip()]
            if index in vector_indexes and isinstance(value, list):
                # pgvector text output stores float32-like values at eight
                # decimal places; compare at the target type's precision.
                value = [
                    float(Decimal(str(item)).quantize(Decimal("0.0000001"), rounding=ROUND_HALF_UP))
                    for item in value
                ]
            normalized.append(_canonical(value))
        digest.update(json.dumps(normalized, ensure_ascii=False, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def sqlite_digest(db_path: Path, table: str, columns: list[str] | None = None) -> str | None:
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as db:
        try:
            db_columns = db.execute(f'PRAGMA table_info("{table}")').fetchall()
            names = [row[1] for row in db_columns]
            if not names:
                return None
            selected = columns or names
            order = "id" if "id" in selected else selected[0]
            projection = ", ".join(f'"{name}"' for name in selected)
            digest = hashlib.sha256()
            if order == "id":
                last_id = -1
                while True:
                    rows = db.execute(
                        f'SELECT {projection} FROM "{table}" WHERE "id" > ? ORDER BY "id" LIMIT {HASH_BATCH_SIZE}',
                        (last_id,),
                    ).fetchall()
                    if not rows:
                        break
                    _update_digest(digest, rows)
                    last_id = rows[-1][selected.index("id")]
                return digest.hexdigest()
            return _digest_rows(db.execute(f'SELECT {projection} FROM "{table}" ORDER BY "{order}"'))
        except sqlite3.Error:
            return None


def sqlite_count(db_path: Path, table: str) -> int | None:
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as db:
        try:
            return int(db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        except sqlite3.Error:
            return None


def validate_sqlite_source(db_path: Path, tables: list[str]) -> None:
    """Fail fast when the compare gate receives an empty or wrong SQLite file."""
    if not db_path.is_file():
        raise SystemExit(f"SQLite source not found: {db_path}")
    if db_path.stat().st_size == 0:
        raise SystemExit(f"SQLite source is empty: {db_path}")
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as db:
        present = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    missing = sorted(set(tables) - present)
    if missing:
        raise SystemExit(
            "SQLite source schema is incompatible; missing expected tables: "
            + ", ".join(missing)
        )


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


def postgres_digest(pg_url: str, table: str, columns: list[str] | None = None) -> str | None:
    engine, text = postgres_engine(pg_url)
    with engine.connect() as conn:
        db_columns = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:table ORDER BY ordinal_position"
        ), {"table": table}).fetchall()
        if not db_columns:
            return None
        selected = columns or [row[0] for row in db_columns]
        order = "id" if "id" in selected else selected[0]
        projection = ", ".join(f'"{column}"' for column in selected)
        digest = hashlib.sha256()
        if order == "id":
            last_id = -1
            while True:
                result = conn.execute(
                    text(f'SELECT {projection} FROM "{table}" WHERE "id" > :last_id ORDER BY "id" LIMIT {HASH_BATCH_SIZE}'),
                    {"last_id": last_id},
                ).fetchall()
                if not result:
                    break
                _update_digest(digest, result)
                last_id = result[-1][selected.index("id")]
            return digest.hexdigest()
        result = conn.execution_options(stream_results=True, max_row_buffer=1000).execute(text(f'SELECT {projection} FROM "{table}" ORDER BY "{order}"'))
        return _digest_rows(result)


_VALID_ROW_FROM = {
    "embeddings": (
        'FROM "embeddings" e JOIN "course_chunks" c ON e."chunk_id" = c."id"'
    ),
    "match_scores": (
        'FROM "match_scores" m '
        'JOIN "project_versions" v ON m."project_version_id" = v."id" '
        'LEFT JOIN "courses" c ON m."course_id" = c."id" '
        'LEFT JOIN "learning_outcomes" lo ON m."lo_id" = lo."id" '
        'LEFT JOIN "course_chunks" ch ON m."chunk_id" = ch."id" '
        'WHERE (m."course_id" IS NULL OR c."id" IS NOT NULL) '
        'AND (m."lo_id" IS NULL OR lo."id" IS NOT NULL) '
        'AND (m."chunk_id" IS NULL OR ch."id" IS NOT NULL)'
    ),
}


def _valid_digest(db_path: Path, table: str, columns: list[str]) -> str | None:
    from_clause = _VALID_ROW_FROM.get(table)
    if not from_clause:
        return sqlite_digest(db_path, table, columns)
    projection = ", ".join(f'e."{column}"' for column in columns) if table == "embeddings" else ", ".join(f'm."{column}"' for column in columns)
    order_alias = "e" if table == "embeddings" else "m"
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as db:
        return _digest_rows_for_table(db.execute(f'SELECT {projection} {from_clause} ORDER BY {order_alias}."id"'), table, columns)


def _valid_postgres_digest(pg_url: str, table: str, columns: list[str]) -> str | None:
    from_clause = _VALID_ROW_FROM.get(table)
    if not from_clause:
        return postgres_digest(pg_url, table, columns)
    projection = ", ".join(f'e."{column}"' for column in columns) if table == "embeddings" else ", ".join(f'm."{column}"' for column in columns)
    order_alias = "e" if table == "embeddings" else "m"
    engine, text = postgres_engine(pg_url)
    with engine.connect() as conn:
        result = conn.execution_options(stream_results=True, max_row_buffer=1000).execute(
            text(f'SELECT {projection} {from_clause} ORDER BY {order_alias}."id"')
        )
        return _digest_rows_for_table(result, table, columns)


def postgres_fk_violations(pg_url: str) -> int:
    engine, text = postgres_engine(pg_url)
    with engine.connect() as conn:
        # Every declared FK is checked by a NOT EXISTS probe.  This remains
        # portable PostgreSQL SQL and reports all violations in one result.
        constraints = conn.execute(text(
            "SELECT tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name=ccu.constraint_name AND tc.table_schema=ccu.table_schema "
            "WHERE tc.table_schema='public' AND tc.constraint_type='FOREIGN KEY'"
        )).fetchall()
        violations = 0
        for table, column, ref_table, ref_column in constraints:
            violations += int(conn.execute(text(
                f'SELECT COUNT(*) FROM "{table}" child LEFT JOIN "{ref_table}" parent '
                f'ON child."{column}"=parent."{ref_column}" '
                f'WHERE child."{column}" IS NOT NULL AND parent."{ref_column}" IS NULL'
            )).scalar() or 0)
        return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path, default=Path("backend/curriculum_kag.db"))
    parser.add_argument("--postgres", required=True, help="postgresql+psycopg2://...")
    parser.add_argument("--tables", nargs="*", default=DEFAULT_TABLES)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--hash", action="store_true", help="Сравнить полный детерминированный digest строк")
    parser.add_argument("--check-fk", action="store_true", help="Проверить FK-нарушения в SQLite и PostgreSQL")
    parser.add_argument(
        "--allow-sqlite-fk-violations",
        action="store_true",
        help="Разрешить известные source-only orphans; PostgreSQL FK must still be clean",
    )
    args = parser.parse_args()
    validate_sqlite_source(args.sqlite, args.tables)

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
        sqlite_hash = postgres_hash = None
        if args.hash:
            with sqlite3.connect(f"file:{args.sqlite.as_posix()}?mode=ro", uri=True) as db:
                sqlite_columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")').fetchall()]
            engine, text = postgres_engine(args.postgres)
            with engine.connect() as conn:
                postgres_columns = [row[0] for row in conn.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=:table ORDER BY ordinal_position"
                ), {"table": table}).fetchall()]
            common_columns = [column for column in sqlite_columns if column in postgres_columns]
            if sqlite_rows != sqlite_valid_rows:
                sqlite_hash = _valid_digest(args.sqlite, table, common_columns)
                postgres_hash = _valid_postgres_digest(args.postgres, table, common_columns)
            else:
                sqlite_hash, postgres_hash = sqlite_digest(args.sqlite, table, common_columns), postgres_digest(args.postgres, table, common_columns)
            row_passed = row_passed and sqlite_hash == postgres_hash
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
                "sqlite_sha256": sqlite_hash,
                "postgres_sha256": postgres_hash,
            }
        )

    sqlite_fk = None
    postgres_fk = None
    if args.check_fk:
        with sqlite3.connect(f"file:{args.sqlite.as_posix()}?mode=ro", uri=True) as db:
            sqlite_fk = len(db.execute("PRAGMA foreign_key_check").fetchall())
        postgres_fk = postgres_fk_violations(args.postgres)
        passed = passed and postgres_fk == 0 and (args.allow_sqlite_fk_violations or sqlite_fk == 0)
    report = {
        "passed": passed,
        "tables": rows,
        "discard_manifest": [
            {"table": row["table"], "rows": row["skipped_orphan_rows"],
             "reason": "derived row references a missing parent in the source snapshot"}
            for row in rows if isinstance(row.get("skipped_orphan_rows"), int) and row["skipped_orphan_rows"] > 0
        ],
        "foreign_key_violations": {"sqlite": sqlite_fk, "postgres": postgres_fk},
        "sqlite_fk_policy": "reviewed_source_orphans_allowed" if args.allow_sqlite_fk_violations else "strict",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
