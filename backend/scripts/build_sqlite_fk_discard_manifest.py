"""Build a reviewable, non-destructive manifest of SQLite FK violations.

The migration must not silently drop rows from a dirty legacy database. This
script records every violation's table/row id and aggregates the failure
classes, so a migration decision can explicitly classify rows as repairable,
discardable derived data, or a hard stop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


# A violating child row has no parent in the source snapshot.  Every entry
# below is therefore unreachable through the product and may only be kept by
# recreating its parent plan/version first.  The migration deliberately skips
# these rows; computed layers are regenerated only after their parent exists.
ORPHAN_ACTIONS = {
    "embeddings": "discard_and_regenerate",
    "match_scores": "discard_and_regenerate",
    "match_feedback": "discard_and_regenerate",
    "bridge_modules": "discard_and_regenerate",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-limit", type=int, default=25)
    args = parser.parse_args()
    if args.sample_limit < 1 or args.sample_limit > 1000:
        raise SystemExit("--sample-limit must be between 1 and 1000")
    if not args.db.is_file():
        raise SystemExit(f"SQLite database not found: {args.db}")

    digest = hashlib.sha256()
    progress_path = args.output.with_suffix(args.output.suffix + ".progress.json")
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_started = time.monotonic()

    def write_progress(phase: str, **details: object) -> None:
        payload = {
            "status": "running",
            "phase": phase,
            "elapsed_seconds": round(time.monotonic() - progress_started, 2),
            **details,
        }
        progress_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    write_progress("hash", bytes_read=0)
    bytes_read = 0
    with args.db.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            bytes_read += len(chunk)
            digest.update(chunk)
            if time.monotonic() - progress_started >= 5:
                write_progress("hash", bytes_read=bytes_read, source_bytes=args.db.stat().st_size)

    with sqlite3.connect(args.db) as con:
        last_progress = time.monotonic()

        def sqlite_progress() -> int:
            nonlocal last_progress
            now = time.monotonic()
            if now - last_progress >= 5:
                write_progress("foreign_key_check", bytes_read=bytes_read)
                last_progress = now
            return 0

        con.set_progress_handler(sqlite_progress, 10_000)
        violations = con.execute("PRAGMA foreign_key_check").fetchall()
        con.set_progress_handler(None, 0)

    by_table = Counter(str(row[0]) for row in violations)
    by_parent = Counter(str(row[2]) for row in violations)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(args.db.resolve()),
        "source_sha256": digest.hexdigest(),
        "policy": {
            "mode": "review_required",
            "destructive_action_performed": False,
            "repair_or_discard_before_postgres_cutover": True,
        },
        "total_violations": len(violations),
        "violations_by_child_table": dict(sorted(by_table.items())),
        "violations_by_parent_table": dict(sorted(by_parent.items())),
        "required_action_by_child_table": {
            table: ORPHAN_ACTIONS.get(table, "review_before_cutover")
            for table in sorted(by_table)
        },
        "sample": [
            {"child_table": row[0], "rowid": row[1], "parent_table": row[2], "foreign_key_index": row[3]}
            for row in violations[: args.sample_limit]
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_progress("complete", bytes_read=bytes_read, total_violations=len(violations))
    print(json.dumps({"output": str(args.output), "total_violations": len(violations), "source_sha256": digest.hexdigest()}, ensure_ascii=False))
    return 0 if not violations else 2


if __name__ == "__main__":
    raise SystemExit(main())
