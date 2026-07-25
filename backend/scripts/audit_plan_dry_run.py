"""Build one plan variant transactionally, audit it, then roll back all writes."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.database import SessionLocal
from app.planner.scheduler import (
    _foundation_equivalent_title_key,
    _is_component_placeholder_title,
    _title_key,
    build_curriculum_plan,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--variant", choices=("A", "B", "C"), default="A")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    db = SessionLocal()
    started = time.perf_counter()
    try:
        result = build_curriculum_plan(args.version, db, args.variant, commit=False)
        rows = [item for items in result["schedule"].values() for item in items]
        exact = {}
        semantic = {}
        placeholders = []
        for item in rows:
            key = _title_key(item.get("title"))
            exact.setdefault(key, []).append(item.get("title"))
            semantic_key = (_foundation_equivalent_title_key(key), int(item.get("credits") or 0))
            semantic.setdefault(semantic_key, []).append(item.get("title"))
            if _is_component_placeholder_title(key):
                placeholders.append(item.get("title"))
        report = {
            "status": "complete",
            "project_version_id": args.version,
            "variant": args.variant,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "total_courses": len(rows),
            "total_credits": sum(int(item.get("credits") or 0) for item in rows),
            "exact_duplicates": [titles for titles in exact.values() if len(titles) > 1],
            "foundation_alias_duplicates": [titles for titles in semantic.values() if len(titles) > 1],
            "component_placeholders": placeholders,
            "semester_details": {
                str(semester): {
                    "credits": sum(int(item.get("credits") or 0) for item in items),
                    "items": [{
                        "title": item.get("title"),
                        "credits": int(item.get("credits") or 0),
                        "course_id": item.get("course_id"),
                        "bridge_module_id": item.get("bridge_module_id"),
                        "type": item.get("type"),
                        "recommended_semester": item.get("recommended_semester"),
                        "latest_semester": item.get("latest_semester"),
                        "regulatory_required": bool(item.get("regulatory_required")),
                        "prerequisites": item.get("prerequisites") or [],
                    } for item in items],
                }
                for semester, items in result["schedule"].items()
            },
            "metrics": result.get("metrics"),
        }
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: report[key] for key in (
            "status", "elapsed_seconds", "total_courses", "total_credits",
            "exact_duplicates", "foundation_alias_duplicates", "component_placeholders",
        )}, ensure_ascii=False))
    except Exception as error:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps({
            "status": "failed", "project_version_id": args.version,
            "variant": args.variant, "elapsed_seconds": round(time.perf_counter() - started, 2),
            "error": f"{type(error).__name__}: {error}",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
