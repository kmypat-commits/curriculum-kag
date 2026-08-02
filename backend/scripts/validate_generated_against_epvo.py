"""Read-only structural validation of generated plans against EPVO curricula.

This is an external-reference comparison, not a substitute for blinded expert
review.  It measures provenance, semester alignment, and overlap with complete
EPVO programme course sets from the same direction/group.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from collections import defaultdict
from statistics import mean, median

from app.database import SessionLocal
from app.models.course import Course
from app.models.epvo import EpvoDisciplineNormalized
from app.models.plan import Plan, PlanItem
from app.models.project import Project


def _scope_match(row: EpvoDisciplineNormalized, groups: set[str], directions: set[str]) -> bool:
    return bool(groups.intersection(row.group_codes or []) or directions.intersection(row.direction_codes or []))


def _bootstrap_ci(values: list[float], seed: int = 42, repetitions: int = 10_000) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(seed)
    estimates = sorted(mean(rng.choice(values) for _ in values) for _ in range(repetitions))
    return [round(estimates[int(0.025 * repetitions)], 4), round(estimates[int(0.975 * repetitions)], 4)]


def evaluate(project_id: int, db, all_epvo_rows: list[EpvoDisciplineNormalized], all_epvo_by_id: dict[int, EpvoDisciplineNormalized]) -> dict:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or not project.versions:
        return {"project_id": project_id, "status": "missing_project_or_version"}
    version = max(project.versions, key=lambda value: value.version_number)
    plan = db.query(Plan).filter(Plan.project_version_id == version.id).order_by(Plan.is_active.desc(), Plan.id.desc()).first()
    if not plan:
        return {"project_id": project_id, "title": project.title, "status": "missing_plan"}

    constraints = project.constraints_json or {}
    max_semesters = int(constraints.get("total_semesters") or 0)
    groups = {str(value) for value in (constraints.get("group_code"), constraints.get("secondary_group_code")) if value}
    directions = {str(value) for value in (constraints.get("direction_code"), constraints.get("secondary_direction_code")) if value}
    scope_rows = [row for row in all_epvo_rows if _scope_match(row, groups, directions)]
    scope_by_id = {row.id: row for row in scope_rows}
    # A canonical approved course may aggregate several EPVO source cards,
    # each with a different recommended semester.  Comparing against one
    # arbitrary row makes the external metric noisy.  Use the median of the
    # matching scope rows, which is robust to one exceptional programme.
    typical_by_course: dict[int, list[int]] = defaultdict(list)
    invalid_typical_rows = 0
    for row in scope_rows:
        if row.approved_course_id and row.typical_semester:
            value = int(row.typical_semester)
            if 1 <= value and (not max_semesters or value <= max_semesters):
                typical_by_course[int(row.approved_course_id)].append(value)
            else:
                invalid_typical_rows += 1

    programme_sets: dict[str, set[int]] = {}
    for row in scope_rows:
        for source_id in row.source_programs or []:
            programme_sets.setdefault(str(source_id), set()).add(row.id)

    items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
    course_ids = [item.course_id for item in items if item.course_id]
    courses = {row.id: row for row in db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()}
    generated_epvo: set[int] = set()
    semester_checks: list[bool] = []
    for item in items:
        course = courses.get(item.course_id)
        code = str(course.course_id or "") if course else ""
        if not code.startswith("EPVO-"):
            continue
        try:
            discipline_id = int(code.split("-", 1)[1])
        except ValueError:
            continue
        generated_epvo.add(discipline_id)
        row = scope_by_id.get(discipline_id) or all_epvo_by_id.get(discipline_id)
        typical_values = typical_by_course.get(int(course.id), []) if course else []
        fallback = int(row.typical_semester) if row and row.typical_semester else None
        if fallback is not None and not (1 <= fallback and (not max_semesters or fallback <= max_semesters)):
            fallback = None
        typical_semester = median(typical_values) if typical_values else fallback
        if typical_semester:
            semester_checks.append(abs(int(item.semester) - int(typical_semester)) <= 1)

    comparisons = []
    for source_id, reference in programme_sets.items():
        intersection = len(generated_epvo.intersection(reference))
        union = len(generated_epvo.union(reference))
        comparisons.append({
            "source_program_id": source_id,
            "reference_courses": len(reference),
            "shared_courses": intersection,
            "jaccard": round(intersection / max(1, union), 4),
            "generated_containment": round(intersection / max(1, len(generated_epvo)), 4),
            "reference_recall": round(intersection / max(1, len(reference)), 4),
        })
    comparisons.sort(key=lambda row: (row["jaccard"], row["shared_courses"]), reverse=True)
    top = comparisons[:5]
    real_items = [item for item in items if item.course_id]
    regulatory_items = [
        item for item in real_items
        if (courses.get(item.course_id).cycle_component or "").lower().startswith("goso_")
    ]
    metrics = plan.metrics_json or {}
    quality = metrics.get("international_quality") or {}
    hard_violations = int(metrics.get("prerequisite_violations") or 0) + int(metrics.get("semester_load_violations") or 0)
    return {
        "project_id": project_id,
        "title": project.title,
        "variant": plan.variant_type,
        "status": "ok",
        "scope": {"groups": sorted(groups), "directions": sorted(directions)},
        "plan_courses": len(real_items),
        "epvo_courses": len(generated_epvo),
        "epvo_provenance": round(len(generated_epvo) / max(1, len(real_items)), 4),
        "regulatory_real_courses_excluded": len(regulatory_items),
        "epvo_provenance_excluding_regulatory": round(
            len(generated_epvo) / max(1, len(real_items) - len(regulatory_items)), 4
        ),
        "semester_alignment_pm1": round(mean(semester_checks), 4) if semester_checks else None,
        "invalid_typical_semester_rows": invalid_typical_rows,
        "reference_programmes": len(programme_sets),
        "best_reference": top[0] if top else None,
        "top5_mean_jaccard": round(mean(row["jaccard"] for row in top), 4) if top else None,
        "top5": top,
        "feasible": bool(metrics.get("feasible")),
        "hard_violations": hard_violations,
        "international_score": quality.get("score"),
        # Atlas-inspired stress cases are intentionally retained as negative
        # controls.  They must be reported, but not averaged with admissible
        # curricula when estimating production quality.
        "quality_eligible": bool(metrics.get("feasible")) and hard_violations == 0 and bool(quality.get("passed")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projects", nargs="+", type=int, default=[13, 15, 16, 19, 135, 136, 137])
    parser.add_argument("--output", default="experiment-results/external-epvo-plan-validation/report.json")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        all_epvo_rows = db.query(EpvoDisciplineNormalized).all()
        all_epvo_by_id = {row.id: row for row in all_epvo_rows}
        projects = [evaluate(project_id, db, all_epvo_rows, all_epvo_by_id) for project_id in args.projects]
    finally:
        db.close()
    valid = [row for row in projects if row.get("status") == "ok"]
    eligible = [row for row in valid if row.get("quality_eligible")]
    rejected = [row for row in valid if not row.get("quality_eligible")]
    provenance_values = [row["epvo_provenance"] for row in valid]
    adjusted_provenance_values = [row["epvo_provenance_excluding_regulatory"] for row in valid]
    semester_values = [row["semester_alignment_pm1"] for row in valid if row["semester_alignment_pm1"] is not None]
    jaccard_values = [row["best_reference"]["jaccard"] for row in valid if row["best_reference"]]
    containment_values = [row["best_reference"]["generated_containment"] for row in valid if row["best_reference"]]
    summary = {
        "project_count": len(valid),
        "quality_eligible_project_count": len(eligible),
        "negative_control_count": len(rejected),
        "mean_epvo_provenance": round(mean(provenance_values), 4) if provenance_values else None,
        "mean_epvo_provenance_excluding_regulatory": round(mean(adjusted_provenance_values), 4) if adjusted_provenance_values else None,
        "epvo_provenance_bootstrap_95ci": _bootstrap_ci(provenance_values),
        "mean_semester_alignment_pm1": round(mean(semester_values), 4) if semester_values else None,
        "semester_alignment_bootstrap_95ci": _bootstrap_ci(semester_values),
        "mean_best_jaccard": round(mean(jaccard_values), 4) if jaccard_values else None,
        "best_jaccard_bootstrap_95ci": _bootstrap_ci(jaccard_values),
        "mean_best_generated_containment": round(mean(containment_values), 4) if containment_values else None,
        "generated_containment_bootstrap_95ci": _bootstrap_ci(containment_values),
        "quality_eligible_mean_epvo_provenance": round(mean([row["epvo_provenance"] for row in eligible]), 4) if eligible else None,
        "quality_eligible_mean_epvo_provenance_excluding_regulatory": round(mean([row["epvo_provenance_excluding_regulatory"] for row in eligible]), 4) if eligible else None,
        "quality_eligible_mean_semester_alignment_pm1": round(mean([row["semester_alignment_pm1"] for row in eligible if row["semester_alignment_pm1"] is not None]), 4) if eligible else None,
        "quality_eligible_invalid_typical_semester_rows": sum(int(row.get("invalid_typical_semester_rows") or 0) for row in eligible),
        "quality_eligible_mean_best_jaccard": round(mean([row["best_reference"]["jaccard"] for row in eligible if row["best_reference"]]), 4) if eligible else None,
        "quality_eligible_mean_generated_containment": round(mean([row["best_reference"]["generated_containment"] for row in eligible if row["best_reference"]]), 4) if eligible else None,
        "interpretation": "Structural comparison with complete EPVO reference curricula; not blinded expert evaluation.",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"summary": summary, "projects": projects}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
