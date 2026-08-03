"""Compare freshly generated plans with EPVO references without persisting them.

Every temporary Plan/PlanItem is rolled back after evaluation.  This separates
the current planner from historical saved plans in the external audit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database import SessionLocal
from app.models.course import Course
from app.models.epvo import EpvoDisciplineNormalized
from app.models.plan import Plan, PlanItem
from app.models.project import Project
from app.planner.scheduler import build_curriculum_plan
from validate_generated_against_epvo import evaluate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projects", nargs="+", type=int, default=[13, 15, 16, 19, 135, 136, 137])
    parser.add_argument("--variants", nargs="+", default=["A"])
    parser.add_argument("--output", type=Path, default=Path("experiment-results/external-epvo-plan-validation/fresh-report.json"))
    args = parser.parse_args()
    db = SessionLocal()
    try:
        def schedule_fingerprint(schedule: dict) -> str:
            values = []
            for semester, items in sorted((schedule or {}).items(), key=lambda pair: int(pair[0])):
                for item in items or []:
                    if not isinstance(item, dict):
                        continue
                    values.append(
                        f"{int(semester)}:{item.get('course_id') or ''}:{item.get('bridge_module_id') or ''}"
                    )
            return "|".join(values)

        rows = db.query(EpvoDisciplineNormalized).filter(
            EpvoDisciplineNormalized.approved_course_id.isnot(None)
        ).all()
        by_id = {
            int(row.approved_course_id): row
            for row in rows
            if row.approved_course_id is not None
        }
        results = []
        for project_id in args.projects:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project or not project.versions:
                results.append({"project_id": project_id, "status": "missing_project_or_version"})
                continue
            version = max(project.versions, key=lambda value: value.version_number)
            for variant in args.variants:
                generated = build_curriculum_plan(version.id, db, variant, commit=False)
                temporary = Plan(
                    project_version_id=version.id,
                    variant_type=variant,
                    metrics_json=generated.get("metrics") or {},
                    is_active=1,
                )
                db.add(temporary)
                db.flush()
                for semester, items in (generated.get("schedule") or {}).items():
                    for item in items:
                        db.add(PlanItem(
                            plan_id=temporary.id,
                            semester=int(semester),
                            course_id=item.get("course_id"),
                            bridge_module_id=item.get("bridge_module_id"),
                            credits=int(item.get("credits") or 0),
                            course_type=item.get("type") or "mandatory",
                            prerequisites_snapshot=item.get("prerequisites") or [],
                        ))
                db.flush()
                results.append(
                    evaluate(project_id, db, rows, by_id)
                    | {
                        "variant_fresh": variant,
                        "schedule_fingerprint": schedule_fingerprint(generated.get("schedule") or {}),
                    }
                )
                db.rollback()
        by_project = {}
        for row in results:
            by_project.setdefault(int(row.get("project_id") or 0), []).append(row)
        for project_rows in by_project.values():
            fingerprints = [row.get("schedule_fingerprint") for row in project_rows]
            distinct = len(fingerprints) == len(set(fingerprints))
            duplicate_variants = []
            for fingerprint in sorted(set(fingerprints)):
                names = [row.get("variant_fresh") for row in project_rows if row.get("schedule_fingerprint") == fingerprint]
                if len(names) > 1:
                    duplicate_variants.append(names)
            for row in project_rows:
                row["variants_are_distinct"] = distinct
                row["duplicate_variants"] = duplicate_variants
        summary_rows = [row for row in results if row.get("quality_eligible")]
        def mean_metric(key: str):
            values = [float(row[key]) for row in summary_rows if row.get(key) is not None]
            return round(sum(values) / len(values), 4) if values else None
        summary = {
            "project_count": len(results),
            "quality_eligible_project_count": len(summary_rows),
            "mean_epvo_provenance": round(sum(float(row.get("epvo_provenance") or 0) for row in summary_rows) / max(1, len(summary_rows)), 4),
            "mean_epvo_provenance_excluding_regulatory": round(sum(float(row.get("epvo_provenance_excluding_regulatory") or 0) for row in summary_rows) / max(1, len(summary_rows)), 4),
            "mean_semester_alignment_pm1": mean_metric("semester_alignment_pm1"),
            "mean_semester_alignment_scoped_median_pm1": mean_metric("semester_alignment_scoped_median_pm1"),
            "mean_semester_alignment_any_source_pm1": mean_metric("semester_alignment_any_source_pm1"),
            "mean_semester_alignment_prereq_adjusted_pm1": mean_metric("semester_alignment_prereq_adjusted_pm1"),
            "mean_semester_alignment_semantic_adjusted_pm1": mean_metric("semester_alignment_semantic_adjusted_pm1"),
            "interpretation": "Fresh transactional planner output; structural comparison, not blinded expert evaluation.",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"summary": summary, "projects": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
