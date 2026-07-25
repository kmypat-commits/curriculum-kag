"""Create safe SQLite indexes for hot Curriculum-KAG planner/API paths.

The script is idempotent and only uses CREATE INDEX IF NOT EXISTS.
It is intentionally separate from app startup: on a large local DB the user
should control when indexes are created.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path


DB = Path(__file__).resolve().parents[1] / "curriculum_kag.db"

INDEXES = [
    (
        "ix_match_scores_project_course_score",
        "CREATE INDEX IF NOT EXISTS ix_match_scores_project_course_score "
        "ON match_scores(project_version_id, course_id, score)",
    ),
    (
        "ix_match_scores_project_lo_score",
        "CREATE INDEX IF NOT EXISTS ix_match_scores_project_lo_score "
        "ON match_scores(project_version_id, lo_id, score)",
    ),
    (
        "ix_plan_items_plan_course",
        "CREATE INDEX IF NOT EXISTS ix_plan_items_plan_course "
        "ON plan_items(plan_id, course_id)",
    ),
    (
        "ix_plan_items_plan_bridge",
        "CREATE INDEX IF NOT EXISTS ix_plan_items_plan_bridge "
        "ON plan_items(plan_id, bridge_module_id)",
    ),
    (
        "ix_plans_version_variant_active",
        "CREATE INDEX IF NOT EXISTS ix_plans_version_variant_active "
        "ON plans(project_version_id, variant_type, is_active, id)",
    ),
    (
        "ix_raw_epvo_los_program_source",
        "CREATE INDEX IF NOT EXISTS ix_raw_epvo_los_program_source "
        "ON raw_epvo_learning_outcomes(program_source_id)",
    ),
]


def main() -> int:
    started = time.perf_counter()
    with sqlite3.connect(DB, timeout=120) as db:
        db.execute("PRAGMA busy_timeout=120000")
        created = []
        for name, sql in INDEXES:
            before = time.perf_counter()
            db.execute(sql)
            created.append({"index": name, "seconds": round(time.perf_counter() - before, 3)})
        db.commit()
    print({"database": str(DB), "elapsed_seconds": round(time.perf_counter() - started, 3), "indexes": created})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
