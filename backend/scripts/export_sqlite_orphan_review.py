"""Export review-required SQLite FK orphan rows without modifying the source."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


REVIEW_TABLES = {"bridge_modules", "match_feedback"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.db.is_file():
        raise SystemExit(f"SQLite source not found: {args.db}")

    source_digest = sha256(args.db.resolve())
    rows_by_table: dict[str, list[dict]] = {}
    violations_by_table: dict[str, int] = {}
    with sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        for table in sorted(REVIEW_TABLES):
            table_violations = [row for row in violations if str(row[0]) == table]
            violations_by_table[table] = len(table_violations)
            rowids = sorted({int(row[1]) for row in table_violations})
            if not rowids:
                rows_by_table[table] = []
                continue
            placeholders = ",".join("?" for _ in rowids)
            rows = connection.execute(
                f"SELECT * FROM \"{table}\" WHERE rowid IN ({placeholders}) ORDER BY rowid",
                rowids,
            ).fetchall()
            rows_by_table[table] = [dict(row) for row in rows]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(args.db.resolve()),
        "source_sha256": source_digest,
        "read_only": True,
        "review_required_tables": sorted(REVIEW_TABLES),
        "violations_by_table": violations_by_table,
        "rows": rows_by_table,
        "decision": "pending_owner_review",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "source_sha256": source_digest,
        "violations_by_table": violations_by_table,
        "decision": payload["decision"],
    }, ensure_ascii=False))
    return 0 if not any(violations_by_table.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
