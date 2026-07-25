"""Reproduce the T6 NSGA-II curriculum experiment from repository data."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import SessionLocal
from app.kag.scoring import compute_all_matches
from app.models.course import Course
from app.models.embedding import MatchScore
from app.models.project import ProjectVersion
from app.planner.international_quality import evaluate_international_quality
from app.planner.nsga2 import optimize_variants
from app.planner.scheduler import schedule_courses
from app.planner.verifier import verify_curriculum_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a reproducible T6 NSGA-II experiment")
    parser.add_argument("project_version_id", type=int)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--population", type=int, default=settings.NSGA2_POPULATION)
    parser.add_argument("--generations", type=int, default=settings.NSGA2_GENERATIONS)
    parser.add_argument("--output", type=Path, default=Path("experiment-results"))
    args = parser.parse_args()

    db = SessionLocal()
    try:
        version = db.query(ProjectVersion).filter(ProjectVersion.id == args.project_version_id).first()
        if not version:
            raise SystemExit(f"Project version {args.project_version_id} not found")
        compute_all_matches(version.id, db)
        project = version.project
        domains = [(project.domain1 or "").lower(), (project.domain2 or "").lower()]
        scored_ids = {row.course_id for row in db.query(MatchScore).filter(MatchScore.project_version_id == version.id).all()}
        courses = db.query(Course).filter(Course.id.in_(scored_ids or {-1})).all()
        seed_ids = [
            course.id for course in courses
            if any(domain and (domain in (course.domain or "").lower() or (course.domain or "").lower() in domain) for domain in domains)
        ]
        constraints = project.constraints_json or {}
        target = int(constraints.get("total_credits", 240))
        semesters = int(constraints.get("total_semesters", 8))
        load = int(constraints.get("max_credits_per_semester", 30))
        rows = []
        for run in range(args.runs):
            seed = args.seed + run
            variants = optimize_variants(
                version, db, seed_ids, target, target + 5,
                population_size=args.population,
                generations=args.generations,
                crossover_probability=settings.NSGA2_CROSSOVER_PROBABILITY,
                mutation_probability=settings.NSGA2_MUTATION_PROBABILITY,
                random_seed=seed,
            )
            for variant, items in variants.items():
                schedule = schedule_courses(items, semesters, load, db)
                verification = verify_curriculum_plan(schedule, version, db)
                quality = evaluate_international_quality(schedule, version, db, verification)
                rows.append({
                    "run": run + 1, "seed": seed, "variant": variant,
                    "total_credits": verification["total_credits"],
                    "feasible": verification["feasible"],
                    "quality_passed": verification["quality_passed"],
                    "min_lo_coverage": verification["min_lo_coverage"],
                    "average_lo_coverage": verification["average_lo_coverage"],
                    "redundancy": verification["redundancy"],
                    "international_quality_score": quality["score"],
                    "course_ids": json.dumps([item.get("course_id") for item in items if item.get("course_id")]),
                })

        args.output.mkdir(parents=True, exist_ok=True)
        stem = f"t6-project-{version.id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        csv_path = args.output / f"{stem}.csv"
        json_path = args.output / f"{stem}.json"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader(); writer.writerows(rows)
        json_path.write_text(json.dumps({
            "project_version_id": version.id,
            "runs": args.runs,
            "base_seed": args.seed,
            "nsga2": {"population": args.population, "generations": args.generations, "crossover": settings.NSGA2_CROSSOVER_PROBABILITY, "mutation": settings.NSGA2_MUTATION_PROBABILITY},
            "rows": rows,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"csv": str(csv_path), "json": str(json_path), "rows": len(rows)}, ensure_ascii=False))
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
