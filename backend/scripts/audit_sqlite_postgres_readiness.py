"""Dependency-free SQLite preflight before PostgreSQL migration."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


KEY_TABLES = [
    "courses",
    "course_localizations",
    "raw_epvo_programs",
    "raw_epvo_disciplines",
    "raw_epvo_learning_outcomes",
    "raw_epvo_expert_checks",
    "epvo_disciplines_normalized",
    "epvo_discipline_lo_links",
    "embeddings",
    "match_scores",
    "plans",
    "plan_items",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="backend/curriculum_kag.db")
    parser.add_argument("--check-fk", action="store_true")
    parser.add_argument("--full-integrity", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys=ON")
    print(f"db={db_path} size_gb={db_path.stat().st_size / 1024**3:.2f}", flush=True)
    for table in KEY_TABLES:
        count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        print(f"table {table} rows={count}", flush=True)

    fk_rows = []
    if args.check_fk:
        fk_rows = con.execute("PRAGMA foreign_key_check").fetchall()
        print(f"foreign_key_violations={len(fk_rows)}", flush=True)
        for row in fk_rows[:20]:
            print("fk_violation", row, flush=True)
    else:
        print("foreign_key_violations=skipped; run with --check-fk for deep FK check", flush=True)

    integrity = "skipped"
    if args.full_integrity:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"integrity_check={integrity}", flush=True)
    else:
        print("integrity_check=skipped; run with --full-integrity for deep SQLite check", flush=True)
    con.close()

    return 0 if (integrity in {"ok", "skipped"}) and not fk_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
