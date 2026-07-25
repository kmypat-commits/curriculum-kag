"""Lightweight progress monitor for the local PostgreSQL shadow migration."""
from __future__ import annotations

import argparse
import json
import re


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres", required=True, help="postgresql+psycopg2://...")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        from sqlalchemy import create_engine, text
    except Exception as exc:
        raise SystemExit(f"SQLAlchemy/PostgreSQL driver is unavailable: {exc}") from exc

    engine = create_engine(args.postgres, pool_pre_ping=True)
    with engine.connect() as connection:
        activity = connection.execute(text(
            "SELECT now() - query_start AS age, state, wait_event_type, wait_event, query "
            "FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid() "
            "ORDER BY query_start DESC LIMIT 5"
        )).mappings().all()
        table_stats = connection.execute(text(
            "SELECT relname, n_live_tup "
            "FROM pg_stat_user_tables "
            "ORDER BY n_live_tup DESC, relname LIMIT 12"
        )).mappings().all()

    parsed_activity = []
    for row in activity:
        query = str(row["query"] or "")
        table = None
        first_id = None
        match = re.search(r'INSERT INTO "?([A-Za-z0-9_]+)"?', query)
        if match:
            table = match.group(1)
        match = re.search(r"VALUES \((\d+),", query)
        if match:
            first_id = int(match.group(1))
        parsed_activity.append({
            "age": str(row["age"]),
            "state": row["state"],
            "wait_event_type": row["wait_event_type"],
            "wait_event": row["wait_event"],
            "table": table,
            "first_id_in_current_batch": first_id,
            "query_preview": query[:180],
        })

    payload = {
        "activity": parsed_activity,
        "table_stats": [
            {"table": row["relname"], "estimated_rows": int(row["n_live_tup"] or 0)}
            for row in table_stats
        ],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if not parsed_activity:
            print("No active migration connection found.")
        for row in parsed_activity:
            print(
                f"{row['state']} {row['age']} "
                f"table={row['table'] or '?'} batch_first_id={row['first_id_in_current_batch'] or '?'} "
                f"wait={row['wait_event_type'] or '-'}:{row['wait_event'] or '-'}"
            )
        if table_stats:
            print("Top table estimates:")
            for row in payload["table_stats"]:
                print(f"- {row['table']}: {row['estimated_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
