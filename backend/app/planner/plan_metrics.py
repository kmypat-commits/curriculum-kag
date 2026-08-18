from __future__ import annotations

from typing import Dict

from app.config import settings
from app.planner.international_quality import evaluate_international_quality
from app.planner.verifier import verify_curriculum_plan


# Increment when the persisted quality/verification contract changes.  Clients
# can then distinguish a current validator result from a legacy JSON snapshot.
PLAN_METRICS_SCHEMA_VERSION = 2


def persisted_metrics_current(metrics: Dict | None) -> bool:
    """Return whether a persisted plan has the complete current evidence contract."""
    metrics = metrics or {}
    admission = metrics.get("course_admission") or {}
    return bool(
        metrics.get("metrics_schema_version") == PLAN_METRICS_SCHEMA_VERSION
        and isinstance(admission, dict)
        and admission.get("passed") is not None
    )


def calculate_plan_metrics(
    schedule,
    selected_courses,
    project_version,
    db,
    verification=None,
) -> Dict:
    """Build the persisted, API-facing quality summary for a plan."""
    verification = verification or verify_curriculum_plan(schedule, project_version, db)
    international_quality = evaluate_international_quality(
        schedule, project_version, db, verification
    )
    persisted_items = [
        item for semester_items in schedule.values() for item in semester_items
    ]
    selection_method = (
        "nsga2"
        if any(item.get("selection_method") == "nsga2" for item in persisted_items)
        else "deterministic_bridge_heuristic"
    )
    optimizer = {
        "name": "NSGA-II" if selection_method == "nsga2" else "Deterministic bridge heuristic",
        "selection_method": selection_method,
    }
    if selection_method == "nsga2":
        optimizer.update({
            "population": settings.NSGA2_POPULATION,
            "generations": settings.NSGA2_GENERATIONS,
            "crossover_probability": settings.NSGA2_CROSSOVER_PROBABILITY,
            "mutation_probability": settings.NSGA2_MUTATION_PROBABILITY,
            "objectives": ["LO coverage", "redundancy", "domain entropy"],
        })
    return {
        "metrics_schema_version": PLAN_METRICS_SCHEMA_VERSION,
        "total_credits": verification["total_credits"],
        "target_credits": verification["target_credits"],
        "total_courses": len(persisted_items),
        "num_bridge_modules": sum(
            1 for item in persisted_items if item.get("bridge_module_id") is not None
        ),
        "lo_coverage_percentage": round(verification["average_lo_coverage"] * 100, 1),
        "min_lo_coverage": verification["min_lo_coverage"],
        "evidence_count": verification["evidence_count"],
        "redundancy": verification["redundancy"],
        "prerequisite_violations": len(verification["prerequisite_violations"]),
        "semester_load_violations": len(verification["semester_load_violations"]),
        "feasible": verification["feasible"],
        "optimizer": optimizer,
        "international_quality": international_quality,
        "verification": verification,
    }
