"""Print a compact, read-only summary of persisted plan variants."""

from __future__ import annotations

import argparse
import json

from sqlalchemy import create_engine, text

from app.config import settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_version_id", type=int)
    args = parser.parse_args()
    engine = create_engine(settings.DATABASE_URL)
    query = text(
        "SELECT id, variant_type, is_active, metrics_json "
        "FROM plans WHERE project_version_id = :version_id ORDER BY id"
    )
    summaries = []
    with engine.connect() as connection:
        for plan_id, variant, active, metrics in connection.execute(
            query, {"version_id": args.project_version_id}
        ):
            if isinstance(metrics, str):
                metrics = json.loads(metrics)
            metrics = metrics or {}
            verification = metrics.get("verification") or {}
            audit = verification.get("pedagogical_audit") or {}
            goso = verification.get("goso_compliance") or {}
            checklist = metrics.get("international_quality") or {}
            summaries.append(
                {
                    "id": plan_id,
                    "variant": variant,
                    "active": bool(active),
                    "total_credits": metrics.get("total_credits"),
                    "feasible": verification.get("feasible"),
                    "hard_violations": verification.get("hard_violation_count"),
                    "quality_passed": verification.get("quality_passed"),
                    "semester_misplacements": audit.get("semester_misplacements", []),
                    "goso_mandatory_credits": goso.get("mandatory_credits"),
                    "international_score": checklist.get("score"),
                }
            )
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
