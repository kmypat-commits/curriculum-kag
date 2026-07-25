"""Copy a Curriculum-KAG SQLite database into an empty PostgreSQL/pgvector DB."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).resolve().parents[1] / 'curriculum_kag.db'}",
)

from sqlalchemy import create_engine, func, select, text
from app.database import Base
from app.models import *  # noqa: F401,F403


VECTOR_COLUMNS = {("embeddings", "vector"), ("match_scores", "vector")}


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
    args = parser.parse_args()
    if not args.target.startswith("postgresql"):
        raise SystemExit("Target must be a PostgreSQL URL")

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
    with source.connect() as source_connection, target.begin() as target_connection:
        # The legacy SQLite schema contains dependency cycles (for example
        # users/roles and course relations), so no single insertion order can
        # satisfy every FK. PostgreSQL is empty here; disable triggers only for
        # this transaction and validate every FK after the copy.
        target_connection.execute(text("SET LOCAL session_replication_role = replica"))
        for table in Base.metadata.sorted_tables:
            rows = source_connection.execute(select(table)).mappings()
            count, batch = 0, []
            foreign_key_values = {}
            for foreign_key in table.foreign_keys:
                remote_column = foreign_key.column
                foreign_key_values[foreign_key.parent.name] = set(
                    source_connection.execute(select(remote_column)).scalars()
                )
            for row in rows:
                orphaned = any(
                    row[local_column] is not None
                    and row[local_column] not in valid_values
                    for local_column, valid_values in foreign_key_values.items()
                )
                if orphaned:
                    skipped_orphans[table.name] = skipped_orphans.get(table.name, 0) + 1
                    continue
                batch.append({
                    column.name: normalize(table.name, column.name, row[column.name])
                    for column in table.columns
                })
                if len(batch) >= args.batch_size:
                    target_connection.execute(table.insert(), batch)
                    count += len(batch)
                    batch = []
            if batch:
                target_connection.execute(table.insert(), batch)
                count += len(batch)
            report[table.name] = count
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
