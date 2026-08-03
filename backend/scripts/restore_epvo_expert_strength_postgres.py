"""Restore averaged EPVO expert strengths into PostgreSQL link evidence.

The legacy normalized import kept every declared link at strength=1.0.  This
transactional repair reads the immutable raw ``expertCheckResults`` arrays,
aggregates repeated external votes, and updates only matching normalized links.
Use ``--dry-run`` to inspect coverage without writing.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict

from sqlalchemy import create_engine, text


def as_score(value: object) -> float | None:
    try:
        value = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return value if value in (0.0, 0.5, 1.0) else None


def level(value: float) -> str:
    if value <= 0:
        return "rejected"
    if value < 0.75:
        return "medium"
    return "strong"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commit-every", type=int, default=10000)
    args = ap.parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")
    engine = create_engine(args.database_url, pool_pre_ping=True)
    stats = Counter()
    # source_key -> normalized discipline ids. A title can be deduplicated
    # into one row, while historical source keys remain programme-specific.
    source_to_ids: dict[str, list[int]] = defaultdict(list)
    with engine.connect() as db:
        for row in db.execute(text("SELECT id, source_keys FROM epvo_disciplines_normalized")):
            for key in row.source_keys or []:
                source_to_ids[str(key)].append(int(row.id))
        update_sql = text("""UPDATE epvo_discipline_lo_links
                           SET strength=:strength, expert_level=:expert_level
                           WHERE discipline_id=:discipline_id
                             AND program_source_id=:program_id
                             AND lo_source_key=:lo_id""")
        raw = db.execute(text(
            "SELECT program_source_id, source_key, payload_json "
            "FROM raw_epvo_disciplines ORDER BY program_source_id, source_key"
        ))
        pending = 0
        for row in raw:
            payload = row.payload_json or {}
            checks: dict[str, list[float]] = defaultdict(list)
            for item in payload.get("expertCheckResults") or []:
                value = as_score(item.get("result"))
                lo_id = item.get("floId")
                if value is None or lo_id is None:
                    continue
                checks[str(lo_id)].append(value)
                stats[f"raw_vote_{value}"] += 1
            if not checks:
                continue
            discipline_ids = source_to_ids.get(str(row.source_key), [])
            if not discipline_ids:
                stats["unmatched_source_key"] += len(checks)
                continue
            for lo_id, votes in checks.items():
                avg = round(sum(votes) / len(votes), 4)
                stats[f"aggregated_{avg}"] += 1
                stats["votes_used"] += len(votes)
                if args.dry_run:
                    continue
                for discipline_id in discipline_ids:
                    result = db.execute(update_sql, {
                        "strength": avg,
                        "expert_level": level(avg),
                        "discipline_id": discipline_id,
                        "program_id": str(row.program_source_id),
                        "lo_id": lo_id,
                    })
                    if result.rowcount:
                        stats["links_updated"] += int(result.rowcount)
                    else:
                        stats["link_not_found"] += 1
                pending += 1
        if not args.dry_run:
            db.commit()
    stats["source_keys"] = len(source_to_ids)
    stats["dry_run"] = int(args.dry_run)
    print(json.dumps(dict(stats), ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
