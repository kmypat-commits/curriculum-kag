"""Read-only post-migration comparison for pgvector float32 tolerance."""

from __future__ import annotations

import argparse
import ast
import json
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, text


def _vector(value):
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    return [float(item) for item in ast.literal_eval(str(value))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--postgres", required=True)
    parser.add_argument("--tolerance", type=float, default=1e-6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sqlite_rows = {}
    with sqlite3.connect(f"file:{args.sqlite.as_posix()}?mode=ro", uri=True) as db:
        for row in db.execute(
            'SELECT e.id,e.chunk_id,e.model_version,e.vector '
            'FROM embeddings e JOIN course_chunks c ON c.id=e.chunk_id ORDER BY e.id'
        ):
            sqlite_rows[int(row[0])] = row
    engine = create_engine(args.postgres)
    postgres_rows = {}
    with engine.connect() as conn:
        for row in conn.execute(text(
            'SELECT e.id,e.chunk_id,e.model_version,e.vector '
            'FROM embeddings e JOIN course_chunks c ON c.id=e.chunk_id ORDER BY e.id'
        )):
            postgres_rows[int(row[0])] = tuple(row)
    mismatches = []
    compared = 0
    max_error = 0.0
    for row_id, left in sqlite_rows.items():
        right = postgres_rows.get(row_id)
        if right is None:
            mismatches.append({"id": row_id, "reason": "missing_postgres_row"})
            continue
        compared += 1
        if left[1:3] != right[1:3]:
            mismatches.append({"id": row_id, "reason": "metadata", "sqlite": left[1:3], "postgres": right[1:3]})
            continue
        lv, rv = _vector(left[3]), _vector(right[3])
        if len(lv) != len(rv):
            mismatches.append({"id": row_id, "reason": "dimension", "sqlite": len(lv), "postgres": len(rv)})
            continue
        error = max((abs(a - b) for a, b in zip(lv, rv)), default=0.0)
        max_error = max(max_error, error)
        if error > args.tolerance:
            mismatches.append({"id": row_id, "reason": "vector_tolerance", "max_abs_error": error})
    report = {
        "passed": not mismatches and len(sqlite_rows) == len(postgres_rows),
        "sqlite_valid_rows": len(sqlite_rows),
        "postgres_valid_rows": len(postgres_rows),
        "rows_compared": compared,
        "tolerance": args.tolerance,
        "max_abs_error": max_error,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
