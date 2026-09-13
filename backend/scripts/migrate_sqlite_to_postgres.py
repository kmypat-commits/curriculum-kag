"""Copy a Curriculum-KAG SQLite database into an empty PostgreSQL/pgvector DB."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).resolve().parents[1] / 'curriculum_kag.db'}",
)

from sqlalchemy import create_engine, func, inspect, or_, select, text
from app.database import Base
from app.models import *  # noqa: F401,F403


VECTOR_COLUMNS = {("embeddings", "vector"), ("match_scores", "vector")}

# Columns introduced after the original SQLite export.  Legacy SQLite files
# are intentionally supported; these values match the PostgreSQL migration
# defaults and keep the source database read-only.
LEGACY_COLUMN_DEFAULTS = {
    ("users", "cli_token_version"): 0,
}


def source_sqlite_path(source_url: str) -> Path | None:
    parsed = urlparse(source_url)
    if parsed.scheme != "sqlite":
        return None
    raw_path = unquote(parsed.path)
    if parsed.netloc and parsed.netloc not in ("", "localhost"):
        raw_path = f"//{parsed.netloc}{raw_path}"
    # urlparse keeps one leading slash for Windows drive-letter URLs
    # (sqlite:///D:/...) and for relative sqlite:///./... URLs.
    if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    elif raw_path.startswith("/./"):
        raw_path = raw_path[1:]
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_orphan_policy(source_url: str, manifest_path: Path | None) -> None:
    source_path = source_sqlite_path(source_url)
    if source_path is None:
        return
    if not source_path.is_file():
        raise SystemExit(f"SQLite source not found: {source_path}")
    with sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True) as connection:
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if not violations:
        return
    if manifest_path is None:
        raise SystemExit(
            f"SQLite source has {len(violations)} FK violations; migration aborted. "
            "Build and review a discard/repair manifest, then pass --orphan-manifest."
        )
    if not manifest_path.is_file():
        raise SystemExit(f"Orphan manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    policy = manifest.get("policy") or {}
    if policy.get("mode") != "review_required" or policy.get("destructive_action_performed") is not False:
        raise SystemExit(
            "Orphan manifest must be review_required and declare destructive_action_performed=false."
        )
    expected_hash = file_sha256(source_path)
    if manifest.get("source_sha256") != expected_hash:
        raise SystemExit("Orphan manifest source_sha256 does not match the SQLite source.")
    if manifest.get("total_violations") != len(violations):
        raise SystemExit("Orphan manifest total_violations does not match the SQLite source.")
    actual_by_table = {}
    for row in violations:
        table_name = str(row[0])
        actual_by_table[table_name] = actual_by_table.get(table_name, 0) + 1
    declared_by_table = manifest.get("violations_by_child_table") or {}
    normalized_declared = {str(key): int(value) for key, value in declared_by_table.items()}
    if normalized_declared != actual_by_table:
        raise SystemExit("Orphan manifest violations_by_child_table does not match the SQLite source.")
    actions = manifest.get("required_action_by_child_table", {})
    non_discardable = sorted({
        str(row[0]) for row in violations
        if actions.get(str(row[0])) != "discard_and_regenerate"
    })
    if non_discardable:
        raise SystemExit(
            "Migration aborted: orphan rows require repair/review before cutover: "
            + ", ".join(non_discardable)
        )


def normalize(table_name, column_name, value):
    if value is None or (table_name, column_name) not in VECTOR_COLUMNS:
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return [float(item) for item in value.strip("[]").split(",") if item.strip()]
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="sqlite:///./curriculum_kag.db")
    parser.add_argument("--target", required=True)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument(
        "--orphan-manifest",
        type=Path,
        help="Reviewed source-specific manifest; required when SQLite has FK orphans",
    )
    args = parser.parse_args()
    if not args.target.startswith("postgresql"):
        raise SystemExit("Target must be a PostgreSQL URL")
    validate_orphan_policy(args.source, args.orphan_manifest)

    source = create_engine(args.source)
    target = create_engine(args.target, pool_pre_ping=True)
    with target.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(target)

    existing = {}
    with target.connect() as connection:
        for table in Base.metadata.sorted_tables:
            existing[table.name] = connection.execute(select(func.count()).select_from(table)).scalar_one()
    nonempty = {name: count for name, count in existing.items() if count}
    if nonempty:
        raise SystemExit("Target is not empty; migration aborted: " + json.dumps(nonempty))

    report, skipped_orphans = {}, {}
    with source.connect() as source_connection, target.connect() as target_connection:
        raw_source = None
        raw_cursor = None
        source_path = source_sqlite_path(args.source)
        if source_path is not None:
            raw_source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
            raw_cursor = raw_source.cursor()
        source_columns = {
            table_name: {column["name"] for column in columns}
            for table_name in Base.metadata.tables
            for columns in [inspect(source).get_columns(table_name)]
        }
        # The legacy SQLite schema contains dependency cycles (for example
        # users/roles and course relations), so no single insertion order can
        # satisfy every FK. PostgreSQL is empty here; disable triggers only for
        # this transaction and validate every FK after the copy.
        for table in Base.metadata.sorted_tables:
            # Commit each table independently so a large raw table cannot keep
            # the entire migration invisible and make the whole import roll
            # back after a late failure.
            with target_connection.begin():
                target_connection.execute(text("SET LOCAL session_replication_role = replica"))
                available_columns = source_columns[table.name]
                selected_columns = [
                    column for column in table.columns if column.name in available_columns
                ]
                def persist_batch(rows: list[dict]) -> None:
                    """Commit one bounded batch so large tables are resumable."""
                    if not rows:
                        return
                    with target.begin() as batch_connection:
                        batch_connection.execute(text("SET LOCAL session_replication_role = replica"))
                        batch_connection.execute(table.insert(), rows)
                # Stream legacy SQLite rows instead of allowing the driver to
                # materialize a 900k+ row result set in memory.
                statement = select(*selected_columns)
                # Keep orphan filtering inside SQLite instead of materializing
                # every referenced key into Python sets.  The latter defeats
                # streaming on large legacy tables (notably EPVO checks).
                for foreign_key in table.foreign_keys:
                    remote_column = foreign_key.column
                    local_column = foreign_key.parent
                    statement = statement.where(or_(
                        local_column.is_(None),
                        select(1).select_from(remote_column.table)
                        .where(remote_column == local_column).exists(),
                    ))
                count, batch = 0, []
                if raw_cursor is not None:
                    compiled = statement.compile(source, compile_kwargs={"literal_binds": True})
                    raw_cursor.execute(str(compiled))
                    column_names = [column.name for column in selected_columns]
                    while True:
                        raw_rows = raw_cursor.fetchmany(args.batch_size)
                        if not raw_rows:
                            break
                        batch.extend([
                            {
                                column.name: normalize(
                                    table.name,
                                    column.name,
                                    raw_row[column_names.index(column.name)] if column.name in available_columns
                                    else LEGACY_COLUMN_DEFAULTS.get((table.name, column.name)),
                                )
                                for column in table.columns
                            }
                            for raw_row in raw_rows
                        ])
                        persist_batch(batch)
                        count += len(batch)
                        batch = []
                else:
                    rows = source_connection.execution_options(
                        stream_results=True,
                        yield_per=args.batch_size,
                        max_row_buffer=args.batch_size,
                    ).execute(statement).mappings()
                    for row in rows:
                        batch.append({
                            column.name: normalize(
                                table.name,
                                column.name,
                                row[column.name] if column.name in available_columns
                                else LEGACY_COLUMN_DEFAULTS.get((table.name, column.name)),
                            )
                            for column in table.columns
                        })
                        if len(batch) >= args.batch_size:
                            persist_batch(batch)
                            count += len(batch)
                            batch = []
                if batch:
                    persist_batch(batch)
                    count += len(batch)
                report[table.name] = count
        if raw_source is not None:
            raw_source.close()
        with target_connection.begin():
            target_connection.execute(text("SET LOCAL session_replication_role = origin"))
        for table in Base.metadata.sorted_tables:
            for foreign_key in table.foreign_keys:
                local_column = foreign_key.parent.name
                remote_table = foreign_key.column.table.name
                remote_column = foreign_key.column.name
                orphan_count = target_connection.execute(text(
                    f'SELECT COUNT(*) FROM "{table.name}" child '
                    f'LEFT JOIN "{remote_table}" parent '
                    f'ON child."{local_column}" = parent."{remote_column}" '
                    f'WHERE child."{local_column}" IS NOT NULL '
                    f'AND parent."{remote_column}" IS NULL'
                )).scalar_one()
                if orphan_count:
                    raise RuntimeError(
                        f"Foreign-key validation failed: {table.name}.{local_column} "
                        f"has {orphan_count} orphan rows"
                    )
        # Explicit IDs do not advance PostgreSQL sequences.
        for table in Base.metadata.sorted_tables:
            if "id" not in table.c:
                continue
            sequence_name = target_connection.execute(
                text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
                {"table_name": table.name},
            ).scalar()
            if sequence_name:
                target_connection.execute(text(
                    f"SELECT setval('{sequence_name}', "
                    f"COALESCE((SELECT MAX(id) FROM \"{table.name}\"), 1), true)"
                ))
        target_connection.commit()

    with target.connect() as connection:
        for table in Base.metadata.sorted_tables:
            copied = connection.execute(select(func.count()).select_from(table)).scalar_one()
            if copied != report[table.name]:
                raise SystemExit(f"Count mismatch for {table.name}: {report[table.name]} != {copied}")
    print(json.dumps({
        "status": "ok", "tables": report,
        "skipped_orphan_rows": skipped_orphans,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
