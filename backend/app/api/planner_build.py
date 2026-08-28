from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import time

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import finish_sql_query_measurement, get_db, start_sql_query_measurement
from app.models.audit import AuditEvent
from app.models.bridge_module import BridgeModule
from app.models.course import Course
from app.models.embedding import MatchFeedback, MatchScore
from app.models.epvo import EpvoDisciplineLoLink, EpvoDisciplineNormalized
from app.models.project import ProjectVersion
from app.models.user import User
from app.planner.scheduler import build_curriculum_plan, calculate_plan_metrics
from app.planner.evidence_preflight import assess_professional_evidence
from app.services.auth import get_current_user
from app.services.plan_reporting import build_change_report as _build_change_report
from app.services.plan_reporting import plan_snapshot as _plan_snapshot
from app.api.planner_state import (
    claim_build_status as _claim_build_status,
    get_build_status as _get_build_status,
    replace_build_status as _replace_build_status,
    set_build_status as _set_build_status,
)


router = APIRouter()
logger = logging.getLogger(__name__)


def _record_build_telemetry(
    db: Session,
    *,
    current_user: User,
    project_version_id: int,
    state: str,
    elapsed_seconds: float,
    timings: dict,
    sql_query_count: int,
    response_payload: dict | None = None,
) -> None:
    """Persist a compact, non-sensitive build measurement in the audit trail."""
    cache_flags = [bool(timings.get("epvo_repository_cached")), bool(timings.get("scoring_cached"))]
    details = {
        "state": state,
        "duration_ms": round(max(0.0, elapsed_seconds) * 1000),
        "stage_timings_seconds": dict(timings),
        "sql_query_count": max(0, int(sql_query_count)),
        "cache_hit_rate": round(sum(cache_flags) / len(cache_flags), 2),
        "response_bytes": len(json.dumps(response_payload or {}, ensure_ascii=False, default=str).encode("utf-8")),
    }
    try:
        db.add(AuditEvent(
            user_id=current_user.id,
            action="planner_build_telemetry",
            entity_type="project_version",
            entity_id=project_version_id,
            details_json=details,
        ))
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Could not persist planner telemetry for version %s", project_version_id, exc_info=True)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return round(ordered[lower], 2)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 2)


def must_reject_variant(verification: dict | None) -> bool:
    """Return whether a generated variant is unsafe to persist.

    This rule deliberately does not depend on the programme jurisdiction.
    Regulatory components can explain an advisory warning, but they can never
    make an infeasible plan, a hard violation, or an LO without a real-course
    confirmation safe to replace the previously saved plan.
    """
    verification = verification or {}
    quality_reasons = {
        str(item.get("reason"))
        for item in (verification.get("quality_violations") or [])
        if isinstance(item, dict)
    }
    # Some quality findings are not optional presentation warnings: a plan
    # with an impossible semester placement or a missing core competency is
    # pedagogically unsafe even when its arithmetic is valid.  Keep softer
    # review hints (for example domain advisory text) non-blocking.
    blocking_quality_reasons = {
        "semester_appropriateness",
        "missing_core_competency_blocks",
        "bridge_module_limit_exceeded",
    }
    return bool(
        not verification.get("feasible")
        or int(verification.get("hard_violation_count") or 0) > 0
        or "lo_without_real_course" in quality_reasons
        or quality_reasons.intersection(blocking_quality_reasons)
    )


def activate_only_plan(plan_rows: list, active_plan_id: int | None):
    """Mark exactly one plan active and return it.

    Partial rebuilds retain non-requested B/C variants.  Their former active
    flag must still be cleared when a newly built variant becomes active.
    """
    active_plan = None
    for plan in plan_rows:
        is_active = bool(active_plan_id is not None and plan.id == active_plan_id)
        plan.is_active = 1 if is_active else 0
        if is_active:
            active_plan = plan
    return active_plan


@router.post("/{project_version_id}/apply-quality-improvements")
async def apply_quality_improvements(
    project_version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply safe, auditable fixes required by the quality checklist.

    The endpoint fixes the actual failed checks and records every change.
    """
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Версия проекта не найдена")

    from app.models.plan import Plan, PlanItem
    from app.planner.international_quality import evaluate_international_quality, project_course_relevance

    project = version.project
    plan = db.query(Plan).filter(
        Plan.project_version_id == project_version_id,
        Plan.is_active == 1,
    ).order_by(Plan.created_at.desc(), Plan.id.desc()).first()
    if not plan:
        plan = db.query(Plan).filter(Plan.project_version_id == project_version_id).order_by(Plan.created_at.desc(), Plan.id.desc()).first()
    plan_course_ids = {
        int(row.course_id) for row in db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
        if row.course_id
    } if plan else set()
    plan_courses = db.query(Course).filter(Course.id.in_(plan_course_ids or {-1})).all()
    relevance = project_course_relevance(version, plan_courses, db)

    updated_courses = 0
    for course in plan_courses:
        if course.id in relevance["relevant_ids"] and not course.assessment_methods:
            course.assessment_methods = [
                "Практические задания (30%)",
                "Анализ кейса (30%)",
                "Итоговый проект или экзамен (40%)",
            ]
            updated_courses += 1

    constraints = dict(project.constraints_json or {})
    old_excluded = {
        int(value) for value in (constraints.get("excluded_course_ids") or [])
        if str(value).isdigit()
    }
    replaceable_unsupported = set(relevance.get("replaceable_unsupported_ids") or relevance["unsupported_ids"])
    protected_regulatory = set(relevance.get("regulatory_ids") or set())
    newly_excluded = replaceable_unsupported - old_excluded
    constraints["excluded_course_ids"] = sorted(old_excluded | replaceable_unsupported)
    project.constraints_json = constraints

    bridge_code = f"QUALITY_BRIDGE_{project_version_id}"
    bridge = db.query(BridgeModule).filter(BridgeModule.course_id == bridge_code).first()
    interdisciplinary = (
        str(constraints.get("program_type") or "standard").lower() in {"interdisciplinary", "joint"}
        and bool((project.domain2 or "").strip())
    )
    bridge_created = bridge is None and interdisciplinary
    if bridge_created:
        lo_codes = [lo.lo_code for lo in version.learning_outcomes]
        bridge = BridgeModule(
            project_version_id=project_version_id,
            course_id=bridge_code,
            title=f"Интеграционный проект: {project.domain1} и {project.domain2}",
            goal="Связать две предметные области программы в одном прикладном проекте.",
            description="Междисциплинарный модуль, созданный по международному чек-листу качества.",
            credits=5,
            recommended_semester=max(1, int((project.constraints_json or {}).get("total_semesters", 8)) - 1),
            learning_outcomes=[f"Интегрировать знания областей {project.domain1} и {project.domain2}"],
            topics=["Постановка междисциплинарной задачи", "Проектирование решения", "Этика и риски", "Защита проекта"],
            prerequisites=[],
            assessment_methods=["Проект (60%)", "Защита и рефлексия (40%)"],
            source_chunks_json=[],
            generation_params_json={"source": "international_quality_bulk_improvement", "deterministic": True},
            target_los=lo_codes,
            created_by=current_user.id,
        )
        db.add(bridge)
        db.flush()

    existing_verification = ((plan.metrics_json or {}).get("verification") if plan else {}) or {}
    has_hard_plan_violations = bool(
        (existing_verification.get("hard_violation_count") or 0) > 0
        or existing_verification.get("prerequisite_violations")
        or existing_verification.get("semester_load_violations")
        or existing_verification.get("credit_violations")
        or existing_verification.get("domain_quota_violations")
    )
    requires_rebuild = bool(newly_excluded or bridge_created or has_hard_plan_violations)
    metrics_refreshed = False
    if plan and not requires_rebuild:
        plan_items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
        schedule = {}
        for item in plan_items:
            schedule.setdefault(int(item.semester or 1), []).append({
                "course_id": item.course_id,
                "bridge_module_id": item.bridge_module_id,
                "credits": int(item.credits or 0),
            })
        metrics = dict(plan.metrics_json or {})
        verification = metrics.get("verification") or {}
        if verification:
            metrics["international_quality"] = evaluate_international_quality(schedule, version, db, verification)
            plan.metrics_json = metrics
            metrics_refreshed = True

    db.add(AuditEvent(
        user_id=current_user.id,
        action="apply_international_quality_improvements",
        entity_type="project_version",
        entity_id=project_version_id,
        details_json={
            "assessment_courses_updated": updated_courses,
            "bridge_created": bridge_created,
            "bridge_module_id": bridge.id if bridge else None,
            "excluded_irrelevant_course_ids": sorted(newly_excluded),
            "protected_regulatory_course_ids": sorted(protected_regulatory),
            "hard_plan_violations_detected": has_hard_plan_violations,
            "requires_rebuild": requires_rebuild,
            "metrics_refreshed": metrics_refreshed,
        },
    ))
    db.commit()
    return {
        "assessment_courses_updated": updated_courses,
        "bridge_created": bridge_created,
        "bridge_module_id": bridge.id if bridge else None,
        "excluded_irrelevant_courses": len(newly_excluded),
        "protected_regulatory_courses": len(protected_regulatory),
        "hard_plan_violations_detected": has_hard_plan_violations,
        "still_requires_expert_review": len(replaceable_unsupported) == 0 and bool(relevance["unsupported_ids"]),
        "requires_rebuild": requires_rebuild,
        "metrics_refreshed": metrics_refreshed,
    }


@router.post("/{project_version_id}/build")
def build_plan(
    project_version_id: int,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Build all three curriculum plan variants"""
    build_started = time.perf_counter()
    sql_measurement = start_sql_query_measurement()
    sql_query_count: int | None = None
    stage_started = build_started
    timings = {}
    claimed = _claim_build_status(
        project_version_id,
        state="running",
        stage="matching",
        progress=5,
        started_at=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=0,
        timings=timings,
    )
    if claimed is None:
        raise HTTPException(status_code=409, detail="Построение вариантов уже выполняется")
    try:
        from app.models.plan import Plan, PlanItem
        from app.kag.scoring import compute_all_matches
        from app.planner.goso import ensure_goso_learning_outcomes
        from app.services.epvo_repository import approve_epvo_candidates
        from app.services.planner_stage_cache import (
            EPVO_CACHE_ACTION, SCORING_CACHE_ACTION, cache_hit,
            epvo_input_signature, remember_cache, scoring_input_signature,
        )
        version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
        if not version:
            raise ValueError("Версия проекта не найдена")
        ensure_goso_learning_outcomes(version, db)
        _set_build_status(project_version_id, stage="epvo_repository", progress=8)
        epvo_signature = epvo_input_signature(version, db)
        epvo_cached = cache_hit(db, version, EPVO_CACHE_ACTION, epvo_signature)
        if epvo_cached:
            epvo_sync = {"created": 0, "linked": 0, "scope": "cached", "cached": True, "translations": {}}
        else:
            epvo_sync = approve_epvo_candidates(version, db)
            epvo_signature = epvo_input_signature(version, db)
            remember_cache(
                db, version, EPVO_CACHE_ACTION, epvo_signature, current_user.id,
                {"created": epvo_sync.get("created", 0), "linked": epvo_sync.get("linked", 0)},
            )
        timings["epvo_repository"] = round(time.perf_counter() - stage_started, 2)
        timings["epvo_repository_cached"] = epvo_cached
        stage_started = time.perf_counter()
        epvo_translations = epvo_sync.pop("translations", {})
        _set_build_status(
            project_version_id, stage="scoring", progress=12,
            elapsed_seconds=round(time.perf_counter() - build_started, 1), timings=dict(timings),
        )
        # Compute matches once before building all variants
        def update_scoring_progress(payload: dict):
            _set_build_status(project_version_id, **payload)
        scoring_signature = scoring_input_signature(version, db)
        scoring_cached = cache_hit(db, version, SCORING_CACHE_ACTION, scoring_signature)
        if not scoring_cached:
            scoring_result = compute_all_matches(project_version_id, db, progress_callback=update_scoring_progress)
            scoring_signature = scoring_input_signature(version, db)
            remember_cache(
                db, version, SCORING_CACHE_ACTION, scoring_signature, current_user.id,
                {"total_matches": scoring_result.get("total_matches", 0), "total_los": scoring_result.get("total_los", 0)},
            )
        timings["scoring"] = round(time.perf_counter() - stage_started, 2)
        timings["scoring_cached"] = scoring_cached
        evidence_preflight = assess_professional_evidence(version, db)
        timings["evidence_preflight"] = evidence_preflight
        if evidence_preflight.get("blocking"):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "insufficient_epvo_lo_evidence",
                    "message": evidence_preflight.get("message"),
                    "message_by_language": {
                        "ru": "Недостаточно подтверждённых EPVO/LO-доказательств для выбранных направлений. Пересчитайте связи дисциплина–РО или подтвердите экспертные связи перед генерацией.",
                        "kk": "Таңдалған бағыттар үшін расталған EPVO/ОН дәлелдері жеткіліксіз. Генерация алдында пән–ОН байланыстарын қайта есептеңіз немесе сарапшы байланыстарын растаңыз.",
                        "en": "There is not enough verified EPVO/LO evidence for the selected fields. Recompute course–LO links or confirm expert links before generation.",
                    },
                    "evidence": evidence_preflight,
                },
            )
        stage_started = time.perf_counter()
        _set_build_status(
            project_version_id, stage="variants", progress=20,
            elapsed_seconds=round(time.perf_counter() - build_started, 1), timings=dict(timings),
        )

        # Replace previous variants only after all new variants are built
        # successfully. This prevents a mix of stale and partial plans.
        old_plans = db.query(Plan).filter(
            Plan.project_version_id == project_version_id
        ).all()
        active_variant = next(
            (plan.variant_type for plan in old_plans if plan.is_active == 1),
            None,
        )
        old_active_plan = next((plan for plan in old_plans if plan.is_active == 1), None)
        old_active_snapshot = _plan_snapshot(old_active_plan, db)

        requested = payload.get("variants") if isinstance(payload, dict) else None
        if requested in (None, "", "all"):
            requested_variants = ["A", "B", "C"]
        elif isinstance(requested, str):
            requested_variants = [item.strip().upper() for item in requested.split(",")]
        else:
            requested_variants = [str(item).strip().upper() for item in requested]
        requested_variants = list(dict.fromkeys(
            item for item in requested_variants if item in {"A", "B", "C"}
        ))
        if not requested_variants:
            raise HTTPException(status_code=422, detail="Выберите хотя бы один вариант плана: A, B или C")

        variants = {}
        for variant_type in requested_variants:
            variant_started = time.perf_counter()
            _set_build_status(
                project_version_id,
                stage=f"variant_{variant_type}_start", progress={"A": 25, "B": 50, "C": 75}[variant_type]
            )
            # Every requested variant must pass through the selector.  Cloning
            # A into B/C made the labels cosmetic and allowed identical plans
            # to pass acceptance.  The scheduler has deterministic
            # variant-specific ranking, so separate runs remain reproducible
            # while producing genuinely different candidates when alternatives
            # exist.
            result = build_curriculum_plan(
                project_version_id,
                db,
                variant_type,
                commit=False,
            )
            variants[variant_type] = result
            timings[f"variant_{variant_type}"] = round(time.perf_counter() - variant_started, 2)
            _set_build_status(
                project_version_id,
                stage=f"variant_{variant_type}",
                progress={"A": 40, "B": 65, "C": 85}[variant_type],
                elapsed_seconds=round(time.perf_counter() - build_started, 1),
                timings=dict(timings),
            )

        rejected_variants = []
        # A/B/C are alternatives, not cosmetic labels.  Reject a build that
        # accidentally persisted the same course/bridge sequence twice; the
        # caller can then request fewer variants or adjust the constraints.
        def _variant_signature(row):
            schedule = row.get("schedule") or {}
            signature = []
            for semester, items in sorted(schedule.items(), key=lambda pair: int(pair[0])):
                for item in items or []:
                    if not isinstance(item, dict):
                        continue
                    signature.append((int(semester), item.get("course_id"), item.get("bridge_module_id")))
            return tuple(signature)

        signatures = {}
        for name, row in variants.items():
            signatures.setdefault(_variant_signature(row), []).append(name)
        for duplicate_names in signatures.values():
            if len(duplicate_names) > 1:
                for duplicate_name in duplicate_names[1:]:
                    rejected_variants.append({
                        "variant": duplicate_name,
                        "hard": 0,
                        "hard_details": ["variant_not_distinct"],
                        "quality_violations": [{
                            "reason": "variant_not_distinct",
                            "variants": duplicate_names,
                        }],
                    })
        for variant_name, result in variants.items():
            verification = result.get("verification") or {}
            # Quality warnings are review guidance, not a generation failure.
            # Only hard feasibility violations may prevent replacing the old
            # plans; otherwise a valid plan could never be saved when one
            # advisory international-quality check is below its threshold.
            # Regulatory KZ plans may retain advisory quality warnings, but
            # no jurisdiction may bypass a hard feasibility failure or a
            # programme LO without real-course evidence.
            if must_reject_variant(verification):
                rejected_variants.append({
                    "variant": variant_name,
                    "hard": int(verification.get("hard_violation_count") or 0),
                    "hard_details": verification.get("hard_violations") or verification.get("violations") or [],
                    "quality_violations": verification.get("quality_violations") or [],
                })
        if rejected_variants:
            summary = "; ".join(
                f"{row['variant']}: hard={row['hard']}, quality={len(row['quality_violations'])}"
                + (f", details={row['hard_details']}" if row.get("hard_details") else "")
                for row in rejected_variants
            )
            raise ValueError(
                "Новые варианты не прошли финальную проверку; старые планы сохранены. "
                + summary
            )

        stage_started = time.perf_counter()
        _set_build_status(
            project_version_id, stage="saving", progress=92,
            elapsed_seconds=round(time.perf_counter() - build_started, 1), timings=dict(timings),
        )
        # A partial build (for example only A) must not destroy the variants
        # that were intentionally kept (B/C). Replace only requested variants;
        # this lets the user generate the remaining variants later in the UI.
        for old_plan in old_plans:
            if old_plan.variant_type in requested_variants:
                db.delete(old_plan)

        def _variant_quality_key(item):
            variant_name, row = item
            metrics = row.get("metrics") or {}
            verification = metrics.get("verification") or {}
            quality = metrics.get("international_quality") or {}
            return (
                1 if verification.get("feasible") else 0,
                -int(verification.get("hard_violation_count") or 0),
                float(quality.get("score") or 0.0),
                float(metrics.get("lo_coverage_percentage") or 0.0),
                -int(metrics.get("num_bridge_modules") or 0),
                1 if active_variant and variant_name == active_variant else 0,
            )

        best_variant = max(variants.items(), key=_variant_quality_key)[0] if variants else active_variant
        active_plan_id = variants[best_variant]["plan_id"] if best_variant and best_variant in variants else None
        remaining_plans = db.query(Plan).filter(
            Plan.project_version_id == project_version_id
        ).all()
        new_active_plan = activate_only_plan(remaining_plans, active_plan_id)

        new_active_snapshot = _plan_snapshot(new_active_plan, db)
        change_report = _build_change_report(old_active_snapshot, new_active_snapshot)

        if epvo_translations:
            from app.services.content_localization import register_course_translations
            register_course_translations(epvo_translations, db)
        db.commit()
        timings["saving"] = round(time.perf_counter() - stage_started, 2)
        _replace_build_status(project_version_id, **{
            "state": "complete",
            "stage": "complete",
            "progress": 100,
            "change_report": change_report,
            "active_variant": best_variant,
            "elapsed_seconds": round(time.perf_counter() - build_started, 1),
            "timings": timings,
        })

        response_payload = {
            "variants": variants,
            "active_variant": best_variant,
            "epvo_repository": epvo_sync,
            "change_report": change_report,
            "descriptions": {
                "A": "Максимальное покрытие результатов обучения",
                "B": "Минимум новых дисциплин",
                "C": "Минимум конфликтов"
            }
        }
        sql_query_count = finish_sql_query_measurement(sql_measurement)
        _record_build_telemetry(
            db,
            current_user=current_user,
            project_version_id=project_version_id,
            state="complete",
            elapsed_seconds=time.perf_counter() - build_started,
            timings=timings,
            sql_query_count=sql_query_count,
            response_payload=response_payload,
        )
        return response_payload
    except HTTPException:
        if sql_query_count is None:
            sql_query_count = finish_sql_query_measurement(sql_measurement)
        db.rollback()
        _replace_build_status(project_version_id, **{
            "state": "failed", "stage": "failed", "progress": 0,
            "error": "Проверка EPVO/LO-доказательств остановила построение до запуска вариантов.",
            "elapsed_seconds": round(time.perf_counter() - build_started, 1),
            "timings": timings,
        })
        _record_build_telemetry(
            db,
            current_user=current_user,
            project_version_id=project_version_id,
            state="rejected",
            elapsed_seconds=time.perf_counter() - build_started,
            timings=timings,
            sql_query_count=sql_query_count,
        )
        raise
    except Exception as e:
        if sql_query_count is None:
            sql_query_count = finish_sql_query_measurement(sql_measurement)
        db.rollback()
        _replace_build_status(project_version_id, **{
            "state": "failed", "stage": "failed", "progress": 0,
            "error": "Не удалось сформировать учебный план",
            "elapsed_seconds": round(time.perf_counter() - build_started, 1),
            "timings": timings,
        })
        _record_build_telemetry(
            db,
            current_user=current_user,
            project_version_id=project_version_id,
            state="failed",
            elapsed_seconds=time.perf_counter() - build_started,
            timings=timings,
            sql_query_count=sql_query_count,
        )
        logger.exception("Plan build failed for project version %s", project_version_id)
        raise HTTPException(status_code=500, detail="Не удалось сформировать учебный план") from e


@router.get("/{project_version_id}/build-status")
async def get_build_status(
    project_version_id: int,
    current_user: User = Depends(get_current_user),
):
    status = _get_build_status(project_version_id)
    if status.get("state") == "running" and status.get("started_at"):
        try:
            started_at = datetime.fromisoformat(status["started_at"])
            status["elapsed_seconds"] = round(
                (datetime.now(timezone.utc) - started_at).total_seconds(), 1
            )
        except (TypeError, ValueError):
            pass
    return status


@router.get("/{project_version_id}/performance")
def get_build_performance(
    project_version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return compact build latency statistics for the project version."""
    rows = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.action == "planner_build_telemetry",
            AuditEvent.entity_type == "project_version",
            AuditEvent.entity_id == project_version_id,
        )
        .order_by(AuditEvent.timestamp.desc())
        .limit(50)
        .all()
    )
    entries = [row.details_json for row in rows if isinstance(row.details_json, dict)]
    durations = [float(row.get("duration_ms") or 0) for row in entries]
    query_counts = [float(row.get("sql_query_count") or 0) for row in entries]
    response_sizes = [float(row.get("response_bytes") or 0) for row in entries]
    cache_rates = [float(row.get("cache_hit_rate") or 0) for row in entries]
    return {
        "sample_size": len(entries),
        "duration_ms": {"p50": _percentile(durations, 0.5), "p95": _percentile(durations, 0.95)},
        "sql_query_count": {"p50": _percentile(query_counts, 0.5), "p95": _percentile(query_counts, 0.95)},
        "response_bytes": {"p50": _percentile(response_sizes, 0.5), "p95": _percentile(response_sizes, 0.95)},
        "cache_hit_rate": round(sum(cache_rates) / len(cache_rates), 3) if cache_rates else None,
        "recent": entries[:10],
    }


@router.post("/{project_version_id}/recompute-matches")
def recompute_matches(
    project_version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recompute discipline-to-LO links after course descriptions/translations change."""
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Версия проекта не найдена")
    claimed = _claim_build_status(project_version_id, state="running", stage="scoring", progress=5)
    if claimed is None:
        raise HTTPException(status_code=409, detail="Построение или пересчёт уже выполняется")
    try:
        from app.kag.scoring import compute_all_matches
        from app.planner.goso import ensure_goso_learning_outcomes
        from app.services.planner_stage_cache import (
            SCORING_CACHE_ACTION, remember_cache, scoring_input_signature,
        )

        ensure_goso_learning_outcomes(version, db)

        def update_scoring_progress(payload: dict):
            _set_build_status(project_version_id, **payload)

        result = compute_all_matches(project_version_id, db, progress_callback=update_scoring_progress)
        remember_cache(
            db, version, SCORING_CACHE_ACTION, scoring_input_signature(version, db), current_user.id,
            {"total_matches": result.get("total_matches", 0), "total_los": result.get("total_los", 0)},
        )
        _replace_build_status(project_version_id, **{
            "state": "complete",
            "stage": "complete",
            "progress": 100,
            "matches": result.get("total_matches", 0),
            "total_los": result.get("total_los", 0),
        })
        db.add(AuditEvent(
            user_id=current_user.id,
            action="recompute_course_lo_matches",
            entity_type="project_version",
            entity_id=project_version_id,
            details_json={
                "total_matches": result.get("total_matches", 0),
                "total_los": result.get("total_los", 0),
                "prediction": result.get("prediction", {}),
            },
        ))
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        _replace_build_status(project_version_id, **{
            "state": "failed", "stage": "failed", "progress": 0,
            "error": "Не удалось пересчитать связи дисциплина–LO",
        })
        logger.exception("Match recomputation failed for project version %s", project_version_id)
        raise HTTPException(status_code=500, detail="Не удалось пересчитать связи дисциплина–LO") from e




@router.post("/{plan_id}/toggle-active")
async def toggle_plan_active(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Toggle a plan as active and deactivate others for the same project version"""
    from app.models.plan import Plan

    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Учебный план не найден")
    verification = (plan.metrics_json or {}).get("verification", {})

    # A selected plan is the published/active curriculum for this version.
    # Keep the plan flag and the version status in sync so dashboards do not
    # continue to show "draft" after a user has approved a variant.
    db.query(Plan).filter(Plan.project_version_id == plan.project_version_id).update({"is_active": 0})
    plan.is_active = 1
    plan.project_version.status = "active"
    db.add(AuditEvent(
        user_id=current_user.id,
        action="activate_plan",
        entity_type="plan",
        entity_id=plan.id,
        details_json={
            "project_version_id": plan.project_version_id,
            "variant_type": plan.variant_type,
            "version_status": "active",
            "activated_with_hard_violations": int(verification.get("hard_violation_count") or 0) > 0,
            "verification_feasible": verification.get("feasible"),
        },
    ))
    db.commit()

    return {
        "message": "Plan activated and project version published",
        "is_active": True,
        "version_status": "active",
    }
