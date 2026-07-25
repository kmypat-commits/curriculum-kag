"""Build A/B/C in one transaction, compare them, and roll everything back."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.database import SessionLocal
from app.planner.scheduler import _title_key, build_curriculum_plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    db = SessionLocal()
    started = time.perf_counter()
    variants = {}
    title_sets = {}
    try:
        for variant in ("A", "B", "C"):
            variant_started = time.perf_counter()
            result = build_curriculum_plan(args.version, db, variant, commit=False)
            rows = [item for items in result["schedule"].values() for item in items]
            titles = {_title_key(item.get("title")) for item in rows if _title_key(item.get("title"))}
            title_sets[variant] = titles
            metrics = result.get("metrics") or {}
            verification = metrics.get("verification") or {}
            pedagogical = verification.get("pedagogical_audit") or {}
            variants[variant] = {
                "elapsed_seconds": round(time.perf_counter() - variant_started, 2),
                "courses": len(rows),
                "credits": sum(int(item.get("credits") or 0) for item in rows),
                "bridges": int(metrics.get("num_bridge_modules") or 0),
                "min_lo_coverage": metrics.get("min_lo_coverage"),
                "quality_score": (metrics.get("international_quality") or {}).get("score"),
                "international_quality_passed": (metrics.get("international_quality") or {}).get("passed"),
                "quality_passed": verification.get("quality_passed"),
                "semester_misplacements": pedagogical.get("semester_misplacements", []),
                "hard_violations": verification.get("hard_violation_count"),
                "goso_compliant": (verification.get("goso_compliance") or {}).get("compliant"),
            }

        comparisons = {}
        for left, right in (("A", "B"), ("A", "C"), ("B", "C")):
            union = title_sets[left] | title_sets[right]
            intersection = title_sets[left] & title_sets[right]
            comparisons[f"{left}_{right}"] = {
                "same": title_sets[left] == title_sets[right],
                "shared": len(intersection),
                "different": len(union - intersection),
                "jaccard": round(len(intersection) / max(len(union), 1), 4),
            }
        report = {
            "status": "complete",
            "project_version_id": args.version,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "variants": variants,
            "comparisons": comparisons,
        }
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
    except Exception as error:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "status": "failed",
            "project_version_id": args.version,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "error": f"{type(error).__name__}: {error}",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
