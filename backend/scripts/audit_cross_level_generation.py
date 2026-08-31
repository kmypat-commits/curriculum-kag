"""Create, build and delete a temporary ГОСО control programme.

The programme and its plans are removed after the audit. EPVO courses approved
into the shared normalized repository are intentionally retained.
"""

from __future__ import annotations

import argparse
import cProfile
import faulthandler
import json
import os
import time
import sys
from pathlib import Path


if os.name == "nt":
    # Disposable cohort workers must report native failures to the parent
    # process instead of opening a modal Windows error dialog.  The parent
    # already retries the isolated audit and records its return code.
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0020 | 0x8000)


from sqlalchemy import text as sqlalchemy_text


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.kag.scoring import compute_all_matches
from app.models.project import LearningOutcome, Project, ProjectVersion
from app.models.course import Course
from app.models.bridge_module import BridgeModule
from app.models.embedding import MatchScore
from app.planner.goso import ensure_goso_learning_outcomes
from app.planner.scheduler import (
    _has_foreign_professional_title,
    build_curriculum_plan,
)
from app.services.epvo_repository import approve_epvo_candidates


PROFESSIONAL_LOS = [
    "Разрабатывать новые методы искусственного интеллекта и проверять их научную обоснованность.",
    "Проектировать воспроизводимые эксперименты, анализировать данные и оценивать надёжность моделей.",
    "Публиковать и аргументированно представлять результаты исследований в области информационных технологий.",
    "Обеспечивать этичность, безопасность и прозрачность интеллектуальных информационных систем.",
    "Руководить исследовательскими проектами и внедрять подтверждённые результаты в профессиональную практику.",
]

BACHELOR_LOS = [
    "Разрабатывать программные и информационные системы для решения профессиональных задач.",
    "Применять алгоритмы, структуры данных и методы анализа данных при создании цифровых решений.",
    "Проектировать архитектуру приложений, базы данных и компьютерные сети.",
    "Обеспечивать информационную безопасность, тестирование и надёжность программных систем.",
    "Работать в команде, управлять ИТ-проектами и представлять результаты профессиональной деятельности.",
]

ICT_MEDICINE_LOS = [
    "Разрабатывать программные компоненты, алгоритмы и архитектуру медицинских информационных систем с учётом клинических процессов и потребностей пациентов.",
    "Применять анализ данных и искусственный интеллект для поддержки клинических и управленческих решений.",
    "Интерпретировать базовые биомедицинские данные совместно с медицинскими специалистами.",
    "Обеспечивать конфиденциальность, безопасность и этичное использование медицинских данных.",
    "Интегрировать цифровые платформы, базы данных и медицинские информационные стандарты.",
    "Проверять качество и безопасность цифровых медицинских решений в междисциплинарной команде.",
]

ICT_AGRO_LOS = [
    "Разрабатывать цифровые платформы, программные сервисы и базы данных для агропромышленного комплекса.",
    "Применять анализ данных, машинное обучение и дистанционный мониторинг для задач точного земледелия.",
    "Интерпретировать агрономические данные, показатели почвы, растений и сельскохозяйственного производства совместно с отраслевыми специалистами.",
    "Проектировать безопасные и устойчивые цифровые решения для управления агротехнологическими процессами.",
    "Интегрировать датчики, геоинформационные системы и информационные платформы в агропромышленные процессы.",
    "Оценивать экономические, экологические и этические последствия внедрения интеллектуальных агротехнологий.",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", choices=("bachelor", "master", "doctorate"), required=True)
    parser.add_argument("--profile", choices=("standard", "ict-medicine", "ict-agro"), default="standard")
    parser.add_argument("--jurisdiction", choices=("KZ", "INTERNATIONAL"), default="KZ")
    parser.add_argument("--output", required=True)
    parser.add_argument("--variants", nargs="+", choices=("A", "B", "C"), default=("A", "B", "C"))
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--profile-stats", action="store_true", help="collect cProfile stats for plan building")
    args = parser.parse_args()
    # A cohort worker can spend minutes inside a native/ML call.  Emit a
    # periodic Python traceback to stderr so the parent can identify the
    # blocked phase instead of recording an opaque timeout only.
    faulthandler.dump_traceback_later(60, repeat=True, file=sys.stderr)
    if args.profile in {"ict-medicine", "ict-agro"}:
        if args.level != "bachelor":
            parser.error("interdisciplinary control profiles currently require --level bachelor")
        total_credits, semesters, direction, group, area = 240, 8, "6B061", "B057", "6B06"
        if args.profile == "ict-medicine":
            secondary_direction, secondary_group, secondary_area = "6B101", "B086", "6B10"
            domain2 = "Здравоохранение"
            professional_los = ICT_MEDICINE_LOS
        else:
            secondary_direction, secondary_group, secondary_area = "6B081", "B077", "6B08"
            domain2 = "Агрономия"
            professional_los = ICT_AGRO_LOS
        domain1 = "Информационно-коммуникационные технологии"
        # Two-domain programmes may require one foundation, one data and one
        # integration module, plus a small credit-balancing module.  The
        # contract therefore limits the number but does not reject a valid
        # interdisciplinary plan merely because it needs these explicit
        # bridges.
        max_allowed_bridges = 5
        min_prerequisite_edges = 6
    elif args.level == "bachelor":
        total_credits, semesters, direction, group, area = 240, 8, "6B061", "B057", "6B06"
        secondary_direction = secondary_group = secondary_area = ""
        domain1, domain2 = "Информационно-коммуникационные технологии", ""
        professional_los = BACHELOR_LOS
        max_allowed_bridges = 2 if args.jurisdiction != "KZ" else 1
        min_prerequisite_edges = 5
    elif args.level == "doctorate":
        total_credits, semesters, direction, group, area = 180, 6, "8D061", "D094", "8D06"
        secondary_direction = secondary_group = secondary_area = ""
        domain1, domain2 = "Информационно-коммуникационные технологии", ""
        professional_los = PROFESSIONAL_LOS
        max_allowed_bridges = 0
        min_prerequisite_edges = 2
    else:
        total_credits, semesters, direction, group, area = 120, 4, "7M061", "M094", "7M06"
        secondary_direction = secondary_group = secondary_area = ""
        domain1, domain2 = "Информационно-коммуникационные технологии", ""
        professional_los = PROFESSIONAL_LOS
        # A master plan may contain one explicit integration bridge when the
        # repository has no exact-credit real course; it is reviewed as a
        # quality signal rather than treated as a generation failure.
        max_allowed_bridges = 1
        min_prerequisite_edges = 3
    constraints = {
        "education_level": args.level,
        "jurisdiction": args.jurisdiction,
        "program_type": "interdisciplinary" if args.profile != "standard" else "standard",
        "education_area": area,
        "direction_code": direction,
        "group_code": group,
        "secondary_education_area": secondary_area,
        "secondary_direction_code": secondary_direction,
        "secondary_group_code": secondary_group,
        "instruction_language": "ru",
        "duration_years": semesters / 2,
        "total_semesters": semesters,
        "total_credits": total_credits,
        # ECTS totals are whole catalogue units (typically 3--6 credits),
        # therefore the acceptance profile uses the same explicit envelope
        # exposed by the UI instead of treating a one-credit remainder as a
        # hard planner defect.
        "credit_tolerance": 3,
        "max_credits_per_semester": 30,
        "min_domain1_percent": 40,
        "min_domain2_percent": 40 if args.profile != "standard" else 0,
        "allow_new_courses": True,
        "max_new_courses": 5,
        "master_track": "scientific_pedagogical",
        "doctorate_track": "scientific_pedagogical",
    }
    db = SessionLocal()
    # Keep disposable cohort audits bounded even when a planner query becomes
    # pathological; this is local to the audit session and never changes the
    # production database setting.
    db.execute(sqlalchemy_text("SET statement_timeout = '240000'"))
    project_id = None
    started = time.perf_counter()
    report = {"level": args.level, "status": "running"}
    try:
        project = Project(
            title=f"AUTOTEST ГОСО {args.level} {args.profile}",
            domain1=domain1,
            domain2=domain2,
            goal="Подготовка исследователей интеллектуальных информационных систем.",
            constraints_json=constraints,
        )
        version = ProjectVersion(project=project, version_number=1, status="draft")
        db.add(project)
        db.flush()
        project_id = project.id
        for index, text in enumerate(professional_los, start=1):
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
        if args.jurisdiction == "KZ":
            ensure_goso_learning_outcomes(version, db)
        repository = approve_epvo_candidates(version, db, limit=500)
        db.commit()
        print(f"repository created={repository.get('created')} linked={repository.get('linked')}", flush=True)
        scoring = compute_all_matches(
            version.id,
            db,
            progress_callback=lambda event: print(
                f"scoring {event.get('stage', 'progress')} "
                f"{event.get('lo_index')}/{event.get('lo_total')} "
                f"{event.get('lo_code')} matches={event.get('matches', 0)}",
                flush=True,
            ),
        )
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
            print(f"plan build start variant={code}", flush=True)
            db.info["planner_trace"] = True
            faulthandler.dump_traceback_later(60, repeat=True, file=sys.stderr)
            profiler = cProfile.Profile() if args.profile_stats else None
            try:
                if profiler:
                    profiler.enable()
                result = build_curriculum_plan(version.id, db, code, commit=False)
            finally:
                if profiler:
                    profiler.disable()
                    profiler.dump_stats(str(ROOT / ".runtime" / f"plan-build-{version.id}-{code}.prof"))
                faulthandler.cancel_dump_traceback_later()
            print(f"plan build finished variant={code}", flush=True)
            metrics = result.get("metrics") or {}
            verification = metrics.get("verification") or {}
            audit = verification.get("pedagogical_audit") or {}
            schedule = result.get("schedule") or {}
            selected_bridge_ids = {
                int(item.get("bridge_module_id"))
                for items in schedule.values()
                for item in items
                if item.get("bridge_module_id") is not None
            }
            selected_real_ids = {
                int(item.get("course_id"))
                for items in schedule.values()
                for item in items
                if item.get("course_id") is not None
                and not item.get("regulatory_required")
            }
            selected_real_courses = {
                course.id: course
                for course in db.query(Course).filter(
                    Course.id.in_(selected_real_ids or {-1})
                ).all()
            }
            credit_integrity_violations = [
                {
                    "course_id": int(item["course_id"]),
                    "title": item.get("title"),
                    "plan_credits": int(item.get("credits") or 0),
                    "repository_credits": int(
                        selected_real_courses[int(item["course_id"])].credits or 5
                    ),
                }
                for items in schedule.values()
                for item in items
                if item.get("course_id") is not None
                and not item.get("regulatory_required")
                and int(item["course_id"]) in selected_real_courses
                and int(item.get("credits") or 0)
                != int(selected_real_courses[int(item["course_id"])].credits or 5)
            ]
            project_domains = [
                str(project.domain1 or ""),
                str(project.domain2 or ""),
            ]
            foreign_professional_titles = [
                {
                    "course_id": int(item["course_id"]),
                    "title": item.get("title"),
                }
                for items in schedule.values()
                for item in items
                if item.get("course_id") is not None
                and not item.get("regulatory_required")
                and int(item["course_id"]) in selected_real_courses
                and _has_foreign_professional_title(
                    selected_real_courses[int(item["course_id"])],
                    project_domains,
                )
            ]
            bridge_rows = {
                bridge.id: bridge
                for bridge in db.query(BridgeModule).filter(
                    BridgeModule.id.in_(selected_bridge_ids or {-1})
                ).all()
            }
            bridge_details = [
                {
                    "id": bridge_id,
                    "code": bridge_rows[bridge_id].course_id,
                    "title": bridge_rows[bridge_id].title,
                    "credits": int(item.get("credits") or bridge_rows[bridge_id].credits or 0),
                    "semester": int(semester),
                    "target_los": bridge_rows[bridge_id].target_los or [],
                    "mode": (bridge_rows[bridge_id].generation_params_json or {}).get("mode"),
                    "generation_params": bridge_rows[bridge_id].generation_params_json or {},
                }
                for semester, items in schedule.items()
                for item in items
                if item.get("bridge_module_id") is not None
                for bridge_id in [int(item.get("bridge_module_id"))]
                if bridge_id in bridge_rows
            ]
            variants[code] = {
                "credits": sum(int(item.get("credits") or 0) for items in schedule.values() for item in items),
                "semester_loads": verification.get("semester_loads"),
                "hard_violations": verification.get("hard_violation_count"),
                "course_lo_violations": verification.get("course_lo_violations"),
                "prerequisite_violations": verification.get("prerequisite_violations"),
                "prerequisite_graph": verification.get("prerequisite_graph") or {},
                "prerequisite_pairs": [
                    {
                        "prerequisite_id": int(prerequisite_id),
                        "prerequisite_title": next(
                            (
                                source.get("title")
                                for source_items in schedule.values()
                                for source in source_items
                                if int(source.get("course_id") or 0) == int(prerequisite_id)
                            ),
                            None,
                        ),
                        "course_id": int(item.get("course_id")),
                        "course_title": item.get("title"),
                        "prerequisite_semester": next(
                            (
                                int(source_semester)
                                for source_semester, source_items in schedule.items()
                                for source in source_items
                                if int(source.get("course_id") or 0) == int(prerequisite_id)
                            ),
                            None,
                        ),
                        "course_semester": int(semester),
                    }
                    for semester, items in schedule.items()
                    for item in items
                    if item.get("course_id") is not None
                    for prerequisite_id in (item.get("prerequisites") or [])
                ],
                "load_violations": verification.get("semester_load_violations"),
                "credit_violations": verification.get("credit_violations"),
                "credit_integrity_violations": credit_integrity_violations,
                "foreign_professional_titles": foreign_professional_titles,
                "domain_quota_violations": verification.get("domain_quota_violations"),
                "quality_violations": verification.get("quality_violations"),
                "lo_without_real_course": audit.get("lo_without_real_course"),
                "weak_courses": audit.get("weak_courses"),
                "structural_foundations": audit.get("structural_foundations"),
                "competency_blocks": audit.get("competency_blocks") or {},
                "quality_passed": verification.get("quality_passed"),
                "goso_compliant": (
                    (verification.get("goso_compliance") or {}).get("compliant")
                    if args.jurisdiction == "KZ" else True
                ),
                "wrong_semester": len(audit.get("semester_misplacements") or []),
                "semester_misplacements": audit.get("semester_misplacements") or [],
                "wrong_level": len((metrics.get("course_admission") or {}).get("wrong_level_courses") or []),
                "bridges": int(metrics.get("num_bridge_modules") or 0),
                "bridge_details": bridge_details,
                "domain_credits": verification.get("domain_credits") or {},
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
            variant_summary = {
                key: variants[code].get(key)
                for key in (
                    "credits",
                    "hard_violations",
                    "quality_passed",
                    "goso_compliant",
                    "wrong_semester",
                    "wrong_level",
                    "bridges",
                    "international_score",
                )
            }
            variant_summary["prerequisite_edges"] = int(
                variants[code]["prerequisite_graph"].get("edge_count") or 0
            )
            variant_summary["credit_integrity_errors"] = len(
                variants[code]["credit_integrity_violations"]
            )
            variant_summary["foreign_context_errors"] = len(
                variants[code]["foreign_professional_titles"]
            )
            print(
                f"variant {code}: "
                + json.dumps(variant_summary, ensure_ascii=False),
                flush=True,
            )
        fingerprints = {
            json.dumps(row["schedule_fingerprint"], ensure_ascii=False)
            for row in variants.values()
        }
        variants_are_distinct = len(fingerprints) == len(variants)
        def bridge_contract(row: dict) -> bool:
            if args.jurisdiction != "KZ":
                # International programmes have no protected ГОСО block.  A
                # deterministic bridge is admissible when it has explicit LO
                # targets, stays inside the credit budget and is not an
                # opaque placeholder.
                details = row.get("bridge_details") or []
                return (
                    len(details) <= max_allowed_bridges
                    and all(bool(item.get("target_los")) for item in details)
                    and all(int(item.get("credits") or 0) > 0 for item in details)
                    and all(1 <= int(item.get("semester") or 0) <= semesters for item in details)
                )
            if args.profile == "standard":
                return row["bridges"] <= max_allowed_bridges
            details = row.get("bridge_details") or []
            real_titles = " ".join(
                str(title or "").casefold()
                for title in (row.get("real_courses") or [])
            )
            has_real_integration = (
                any(marker in real_titles for marker in (
                    "искусственн интеллект", "цифров", "данн",
                    "информационн технолог",
                ))
                and any(marker in real_titles for marker in (
                    "медицин", "здравоохран", "клиническ",
                ))
            )
            meaningful = [
                item for item in details
                if (
                    (
                        str(item.get("code") or "").startswith("CORE_BRIDGE_")
                        and item.get("mode") == "core_interdisciplinary_bridge"
                    )
                    or (
                        str(item.get("code") or "").startswith("SECONDARY_")
                        and item.get("mode") == "secondary_domain_foundation"
                    )
                )
            ]
            generic = [
                item for item in details
                if str(item.get("code") or "").startswith(
                    ("AUTO_BRIDGE_", "QUALITY_BRIDGE_", "AUTO_BALANCE_", "AUTO_LOAD_SHIFT_")
                )
            ]
            allowed_credit_repair = [
                item for item in generic
                if item.get("mode") == "final_credit_and_load_repair"
            ]
            return (
                len(details) <= max_allowed_bridges
                and len(meaningful) + len(allowed_credit_repair) == len(details)
                and (
                    has_real_integration
                    or any(
                        str(item.get("code") or "").startswith("CORE_BRIDGE_")
                        for item in meaningful
                    )
                )
                and len(allowed_credit_repair) <= 1
                and len(generic) == len(allowed_credit_repair)
                and all(bool(item.get("target_los")) for item in meaningful)
                and all(
                    (1 if str(item.get("code") or "").startswith("SECONDARY_FOUNDATION_") else 2)
                    <= int(item.get("semester") or 0) <= semesters - 1
                    for item in meaningful
                )
            )
        report.update({
            "profile": args.profile,
            "jurisdiction": args.jurisdiction,
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
            "max_allowed_bridges": max_allowed_bridges,
            "min_prerequisite_edges": min_prerequisite_edges,
            "passed": variants_are_distinct and all(
                row["credits"] == total_credits
                and row["hard_violations"] == 0
                and not row["credit_integrity_violations"]
                and not row["foreign_professional_titles"]
                and bridge_contract(row)
                and int(row["prerequisite_graph"].get("edge_count") or 0) >= min_prerequisite_edges
                and row["quality_passed"] is True
                and (row["competency_blocks"].get("passed") is not False)
                and row["goso_compliant"] is True
                and row["wrong_semester"] == 0
                and row["wrong_level"] == 0
                for row in variants.values()
            ),
        })
    except Exception as error:
        report.update({
            "status": "failed",
            "level": args.level,
            "profile": args.profile,
            "jurisdiction": args.jurisdiction,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "error": f"{type(error).__name__}: {error}",
        })
        raise
    finally:
        faulthandler.cancel_dump_traceback_later()
        # ``--keep`` is an explicit debugging option: retain the generated
        # temporary project so its schedule can be inspected after a failed
        # control run.  The default remains rollback + cleanup.
        if args.keep and report.get("status") == "complete":
            db.commit()
        else:
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
