"""Transactional structural audit for ГОСО РК completion blocks."""
from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.models.project import Project, ProjectVersion
from app.planner.goso import ensure_goso_items, evaluate_goso_compliance
from app.planner.scheduler import schedule_courses


CASES = [
    ("bachelor_240", {"education_level": "bachelor", "total_semesters": 8, "total_credits": 240}),
    ("master_professional_60", {"education_level": "master", "master_track": "professional", "total_semesters": 2, "total_credits": 60}),
    ("master_professional_90", {"education_level": "master", "master_track": "professional", "total_semesters": 3, "total_credits": 90}),
    ("master_scientific_120", {"education_level": "master", "master_track": "scientific_pedagogical", "total_semesters": 4, "total_credits": 120}),
    ("doctorate_scientific_180", {"education_level": "doctorate", "doctorate_track": "scientific_pedagogical", "total_semesters": 6, "total_credits": 180}),
    ("doctorate_professional_180", {"education_level": "doctorate", "doctorate_track": "professional", "total_semesters": 6, "total_credits": 180}),
]


def run_case(name: str, values: dict) -> dict:
    db = SessionLocal()
    try:
        constraints = {
            "jurisdiction": "KZ",
            "program_type": "standard",
            "max_credits_per_semester": 30,
            **values,
        }
        project = Project(title=f"AUDIT {name}", domain1="audit", domain2="audit", constraints_json=constraints)
        version = ProjectVersion(project=project, version_number=1, status="draft")
        db.add(project)
        db.flush()
        items = ensure_goso_items(version, db)
        schedule = schedule_courses(items, constraints["total_semesters"], 30, db)
        loads = {semester: sum(int(item.get("credits") or 0) for item in rows) for semester, rows in schedule.items()}
        regulatory_credits = {
            semester: sum(
                int(item.get("credits") or 0)
                for item in rows
                if item.get("regulatory_required")
            )
            for semester, rows in schedule.items()
        }
        # Mirror the verifier's narrow doctoral exception: a semester carrying
        # a full protected 20-credit research block is not rejected solely for
        # exceeding the generic 27--33 band. Ordinary semesters remain capped.
        goso_load_exemptions = sorted(
            semester
            for semester, credits in regulatory_credits.items()
            if values["education_level"] == "doctorate" and credits >= 20
        )
        compliance = evaluate_goso_compliance(schedule, version)
        final_semester = constraints["total_semesters"]
        final_items = [item for item in schedule[final_semester] if item.get("type") == "goso_final"]
        return {
            "case": name,
            "required_credits": sum(int(item.get("credits") or 0) for item in items),
            "semester_loads": loads,
            "items_by_semester": {
                semester: [f"{item.get('title')} ({item.get('credits')})" for item in rows]
                for semester, rows in schedule.items()
            },
            "maximum_load": max(loads.values(), default=0),
            "goso_load_exemptions": goso_load_exemptions,
            "final_in_last_semester": bool(final_items),
            "compliant": compliance["compliant"],
            "violations": compliance["violations"],
        }
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    results = [run_case(name, values) for name, values in CASES]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if not all(
        row["compliant"] and row["final_in_last_semester"] and all(
            load <= 33 or semester in row["goso_load_exemptions"]
            for semester, load in row["semester_loads"].items()
        )
        for row in results
    ):
        raise SystemExit(1)
