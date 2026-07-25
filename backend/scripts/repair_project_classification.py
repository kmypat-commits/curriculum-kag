"""Repair a project's EPVO classification while preserving an audit record."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id", type=int)
    parser.add_argument("--area", required=True)
    parser.add_argument("--direction", required=True)
    parser.add_argument("--group", required=True)
    args = parser.parse_args()
    database = ROOT / "backend" / "curriculum_kag.db"
    db = sqlite3.connect(database)
    row = db.execute("SELECT title,constraints_json FROM projects WHERE id=?", (args.project_id,)).fetchone()
    if not row:
        raise SystemExit("Проект не найден")
    before = json.loads(row[1] or "{}")
    after = dict(before)
    after.update(education_area=args.area, direction_code=args.direction, group_code=args.group)
    db.execute("UPDATE projects SET constraints_json=? WHERE id=?", (json.dumps(after, ensure_ascii=False), args.project_id))
    db.commit(); db.close()
    audit = {
        "changed_at": datetime.now(timezone.utc).isoformat(), "project_id": args.project_id,
        "title": row[0], "before": before, "after": after,
    }
    output = ROOT / "backend" / "experiment-results" / f"project-{args.project_id}-classification-repair.json"
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"project_id": args.project_id, "area": args.area, "direction": args.direction, "group": args.group, "audit": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
