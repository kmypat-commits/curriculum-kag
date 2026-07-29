"""Create, build and delete a temporary ГОСО control programme.

The programme and its plans are removed after the audit. EPVO courses approved
into the shared normalized repository are intentionally retained.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.database import SessionLocal
from app.kag.scoring import compute_all_matches
from app.models.project import LearningOutcome, Project, ProjectVersion
from app.models.course import Course
from app.models.embedding import MatchScore
from app.planner.goso import ensure_goso_learning_outcomes
from app.planner.scheduler import build_curriculum_plan
from app.services.epvo_repository import approve_epvo_candidates


PROFESSIONAL_LOS = [
    "Разрабатывать новые методы искусственного интеллекта и проверять их научную обоснованность.",
    "Проектировать воспроизводимые эксперименты, анализировать данные и оценивать надёжность моделей.",
    "Публиковать и аргументированно представлять результаты исследований в области информационных технологий.",
    "Обеспечивать этичность, безопасность и прозрачность интеллектуальных информационных систем.",
    "Руководить исследовательскими проектами и внедрять подтверждённые результаты в профессиональную практику.",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", choices=("master", "doctorate"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--variants", nargs="+", choices=("A", "B", "C"), default=("A", "B", "C"))
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.level == "doctorate":
        total_credits, semesters, direction, group, area = 180, 6, "8D061", "D094", "8D06"
    else:
        total_credits, semesters, direction, group, area = 120, 4, "7M061", "M094", "7M06"
    constraints = {
        "education_level": args.level,
        "jurisdiction": "KZ",
        "program_type": "standard",
        "education_area": area,
        "direction_code": direction,
        "group_code": group,
        "instruction_language": "ru",
        "duration_years": semesters / 2,
        "total_semesters": semesters,
        "total_credits": total_credits,
        "credit_tolerance": 0,
        "max_credits_per_semester": 30,
        "min_domain1_percent": 40,
        "min_domain2_percent": 0,
        "allow_new_courses": True,
        "max_new_courses": 5,
        "master_track": "scientific_pedagogical",
        "doctorate_track": "scientific_pedagogical",
    }
    db = SessionLocal()
    project_id = None
    started = time.perf_counter()
    report = {"level": args.level, "status": "running"}
    try:
        project = Project(
            title=f"AUTOTEST ГОСО {args.level}",
            domain1="Информационно-коммуникационные технологии",
            domain2="",
            goal="Подготовка исследователей интеллектуальных информационных систем.",
            constraints_json=constraints,
        )
        version = ProjectVersion(project=project, version_number=1, status="draft")
        db.add(project)
        db.flush()
        project_id = project.id
        for index, text in enumerate(PROFESSIONAL_LOS, start=1):
            db.add(LearningOutcome(
                project_version=version,
                lo_code=f"LO{index}",
                lo_text=text,
                taxonomy_level="create" if index in {1, 5} else "evaluate",
                order_index=index,
            ))
        db.commit()
        db.refresh(version)
        print(f"created project={project_id} version={version.id}", flush=True)
        ensure_goso_learning_outcomes(version, db)
        repository = approve_epvo_candidates(version, db, limit=500)
        db.commit()
        print(f"repository created={repository.get('created')} linked={repository.get('linked')}", flush=True)
        scoring = compute_all_matches(version.id, db)
        print(f"scoring matches={scoring.get('total_matches')} los={scoring.get('total_los')}", flush=True)
        match_diagnostics = {}
        for lo in db.query(LearningOutcome).filter(
            LearningOutcome.project_version_id == version.id,
            ~LearningOutcome.lo_code.like("LO-GOSO-%"),
        ).order_by(LearningOutcome.order_index).all():
            top = db.query(MatchScore, Course).join(Course, Course.id == MatchScore.course_id).filter(
                MatchScore.project_version_id == version.id,
                MatchScore.lo_id == lo.id,
            ).order_by(MatchScore.score.desc()).limit(5).all()
            match_diagnostics[lo.lo_code] = [{
                "course_id": course.id,
                "title": course.title,
                "domain": course.domain,
                "score": round(float(match.score or 0), 4),
                "expert_score": round(float((match.evidence_json or {}).get("epvo_expert_score") or 0), 4),
            } for match, course in top]
        variants = {}
        for code in args.variants:
            result = build_curriculum_plan(version.id, db, code, commit=False)
            metrics = result.get("metrics") or {}
            verification = metrics.get("verification") or {}
            audit = verification.get("pedagogical_audit") or {}
            schedule = result.get("schedule") or {}
            variants[code] = {
                "credits": sum(int(item.get("credits") or 0) for items in schedule.values() for item in items),
                "semester_loads": verification.get("semester_loads"),
                "hard_violations": verification.get("hard_violation_count"),
                "course_lo_violations": verification.get("course_lo_violations"),
                "prerequisite_violations": verification.get("prerequisite_violations"),
                "load_violations": verification.get("semester_load_violations"),
                "credit_violations": verification.get("credit_violations"),
                "domain_quota_violations": verification.get("domain_quota_violations"),
                "quality_violations": verification.get("quality_violations"),
                "lo_without_real_course": audit.get("lo_without_real_course"),
                "weak_courses": audit.get("weak_courses"),
                "structural_foundations": audit.get("structural_foundations"),
                "quality_passed": verification.get("quality_passed"),
                "goso_compliant": (verification.get("goso_compliance") or {}).get("compliant"),
                "wrong_semester": len(audit.get("semester_misplacements") or []),
                "semester_misplacements": audit.get("semester_misplacements") or [],
                "wrong_level": len((metrics.get("course_admission") or {}).get("wrong_level_courses") or []),
                "bridges": int(metrics.get("num_bridge_modules") or 0),
                "international_score": (metrics.get("international_quality") or {}).get("score"),
                "real_courses": [
                    item.get("title")
                    for items in schedule.values()
                    for item in items
                    if item.get("course_id") and not item.get("regulatory_required")
                ],
                "real_course_semesters": [
                    {
                        "semester": int(semester),
                        "course_id": item.get("course_id"),
                        "title": item.get("title"),
                        "credits": int(item.get("credits") or 0),
                        "recommended_semester": item.get("recommended_semester"),
                        "variant_preferred_semester": item.get("variant_preferred_semester"),
                        "latest_semester": item.get("latest_semester"),
                    }
                    for semester, items in schedule.items()
                    for item in items
                    if item.get("course_id") and not item.get("regulatory_required")
                ],
                "bridge_titles": [
                    item.get("title")
                    for items in schedule.values()
                    for item in items
                    if item.get("bridge_module_id")
                ],
                "schedule_fingerprint": sorted(
                    (
                        int(semester),
                        str(item.get("title") or ""),
                        int(item.get("credits") or 0),
                    )
                    for semester, items in schedule.items()
                    for item in items
                ),
            }
            print(f"variant {code}: {variants[code]}", flush=True)
        fingerprints = {
            json.dumps(row["schedule_fingerprint"], ensure_ascii=False)
            for row in variants.values()
        }
        variants_are_distinct = len(fingerprints) == len(variants)
        report.update({
            "status": "complete",
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "scope": {"direction": direction, "group": group},
            "repository": {key: repository.get(key) for key in ("created", "linked", "scope")},
            "scoring": {key: scoring.get(key) for key in ("total_matches", "total_los")},
            "match_diagnostics": match_diagnostics,
            "temporary_project_id": project_id if args.keep else None,
            "temporary_version_id": version.id if args.keep else None,
            "variants": variants,
            "variants_are_distinct": variants_are_distinct,
            "passed": variants_are_distinct and all(
                row["credits"] == total_credits
                and row["hard_violations"] == 0
                and row["quality_passed"] is True
                and row["goso_compliant"] is True
                and row["wrong_semester"] == 0
                and row["wrong_level"] == 0
                for row in variants.values()
            ),
        })
    except Exception as error:
        report.update({
            "status": "failed",
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "error": f"{type(error).__name__}: {error}",
        })
        raise
    finally:
        db.rollback()
        if project_id is not None and not args.keep:
            temporary = db.get(Project, project_id)
            if temporary is not None:
                db.delete(temporary)
                db.commit()
        db.close()
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "level": report.get("level"),
            "status": report.get("status"),
            "passed": report.get("passed", False),
            "elapsed_seconds": report.get("elapsed_seconds"),
            "output": str(path),
        }, ensure_ascii=False), flush=True)
    if not report.get("passed", False):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
