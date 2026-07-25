"""Fast SQLite audit for persisted curriculum-plan quality.

The script is intentionally dependency-free: it uses sqlite3 only and checks
stored plan metrics after generation. It is not a replacement for the planner
verifier; it is a cheap regression smoke test for local work.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="backend/curriculum_kag.db")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument(
        "--latest-per-version",
        action="store_true",
        help="Check only the latest plan row for each project version and variant.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    if args.latest_per_version:
        rows = con.execute(
            """
            select p.id, p.project_version_id, p.variant_type, p.is_active, p.metrics_json
            from plans p
            join (
                select project_version_id, variant_type, max(id) as max_id
                from plans
                group by project_version_id, variant_type
            ) latest on latest.max_id = p.id
            order by p.id desc
            limit ?
            """,
            (args.limit,),
        ).fetchall()
    else:
        rows = con.execute(
            """
            select id, project_version_id, variant_type, is_active, metrics_json
            from plans
            order by id desc
            limit ?
            """,
            (args.limit,),
        ).fetchall()

    failures = []
    print(f"db={db_path} plans_checked={len(rows)}")
    for row in rows:
        metrics = json.loads(row["metrics_json"] or "{}")
        verification = metrics.get("verification") or {}
        admission = metrics.get("course_admission") or {}
        quality = metrics.get("international_quality") or {}
        hard = int(verification.get("hard_violation_count") or 0)
        feasible = bool(verification.get("feasible"))
        admission_passed = admission.get("passed")
        score = quality.get("score")
        status = "OK" if feasible and hard == 0 and admission_passed is not False else "CHECK"
        print(
            f"{status} plan={row['id']} pv={row['project_version_id']} "
            f"variant={row['variant_type']} active={row['is_active']} "
            f"feasible={feasible} hard={hard} admission={admission_passed} iq={score}"
        )
        if status != "OK":
            failures.append(row["id"])

    con.close()
    if failures:
        print("plans_need_attention=" + ",".join(map(str, failures)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
