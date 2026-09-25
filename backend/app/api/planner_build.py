from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import finish_sql_query_measurement, get_db, start_sql_query_measurement
from app.models.audit import AuditEvent
from app.models.bridge_module import BridgeModule
from app.models.course import Course
from app.models.embedding import MatchFeedback, MatchScore
from app.models.epvo import EpvoDisciplineLoLink, EpvoDisciplineNormalized
from app.models.project import ProjectVersion
from app.models.plan import Plan, PlanItem
from app.models.plan_build_status import PlanBuildStatus
from app.models.user import User
from app.planner.scheduler import build_curriculum_plan, calculate_plan_metrics
from app.planner.joint_contract import PlanningFailure
from app.planner.invariant_ledger import schedule_fingerprint
from app.planner.evidence_preflight import assess_professional_evidence
from app.planner.selection_evidence import build_selection_evidence_snapshot
from app.services.auth import get_current_user
from app.services.rbac import require_permission
from app.services.access import require_plan_access, require_plan_object_access, require_version_access
from app.services.planner_drafts import (
    build_rejected_draft_payloads,
    draft_summary,
    persist_rejected_drafts,
)
from app.services.plan_reporting import build_change_report as _build_change_report
from app.services.plan_reporting import plan_snapshot as _plan_snapshot
from app.services.program_spec_snapshot import build_program_spec_snapshot, program_spec_hash
from app.api.planner_state import (
    claim_build_status as _claim_build_status,
    get_build_status as _get_build_status,
    replace_build_status as _replace_build_status,
    set_build_status as _set_build_status,
    touch_build_lease as _touch_build_lease,
    cancellation_requested as _cancellation_requested,
    request_build_cancel as _request_build_cancel,
)
from app.api.planner_build_contracts import (
    activate_only_plan,
    build_request_hash,
    generation_readiness,
    must_reject_variant,
    normalize_requested_variants,
    partition_publishable_variants,
)
from app.api.planner_variant_runner import run_requested_variants
from app.schemas.planner import (
    PlannerBuildCancelResponse,
    PlannerBuildRequest,
    PlannerBuildQueuedResponse,
    PlannerBuildResponse,
    PlannerBuildPerformanceResponse,
    PlannerObservabilityResponse,
    PlannerBuildStatusResponse,
)


router = APIRouter()
logger = logging.getLogger(__name__)

# Compatibility name kept for existing route-contract tests and integrations.
_build_request_hash = build_request_hash


class BuildCancelled(RuntimeError):
    """Internal control flow for a user-requested cancellation."""


class BuildInfeasible(ValueError):
    """The requested plan cannot pass final curriculum constraints."""

    def __init__(self, message: str, *, details: list[dict] | None = None, drafts: list[dict] | None = None):
        super().__init__(message)
        self.details = details or []
        self.drafts = drafts or []


@router.get("/{project_version_id}/generation-readiness")
def get_generation_readiness(
    project_version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Report user-correctable input gaps before starting scoring/selection."""
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Версия проекта не найдена")
    project = version.project
    readiness = generation_readiness(
        project.constraints_json,
        goal=project.goal,
        learning_outcomes_count=len(version.learning_outcomes or []),
        learning_outcomes=[outcome.lo_text for outcome in (version.learning_outcomes or [])],
    )
    # Existing MatchScore rows are useful early warning evidence, but are not
    # a safe hard gate here: a user may have just changed the programme and a
    # fresh build is allowed to recompute them. The worker remains the only
    # authority that can reject a build after it has refreshed the evidence.
    has_existing_evidence = db.query(MatchScore.id).filter(
        MatchScore.project_version_id == version.id
    ).first() is not None
    if has_existing_evidence:
        evidence = assess_professional_evidence(version, db)
        readiness["evidence_preflight"] = {
            **evidence,
            "checked": True,
            "advisory": True,
        }
    else:
        readiness["evidence_preflight"] = {
            "checked": False,
            "advisory": True,
            "blocking": False,
            "message": "Связи дисциплина–РО будут рассчитаны в начале построения; предварительная проверка доказательств пока недоступна.",
        }
    return readiness


@router.get("/{project_version_id}/drafts")
def get_rejected_drafts(
    project_version_id: int,
    limit: int = 5,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the owner's non-publishable working drafts."""
    from app.models.planner_draft import PlannerBuildDraft

    require_version_access(db, current_user, project_version_id)
    rows = db.query(PlannerBuildDraft).filter(
        PlannerBuildDraft.project_version_id == project_version_id,
    ).order_by(PlannerBuildDraft.id.desc()).limit(max(1, min(int(limit), 20))).all()
    return {"drafts": [draft_summary(row) for row in rows]}


@router.get("/{project_version_id}/drafts/{draft_id}")
def get_rejected_draft(
    project_version_id: int,
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return one frozen working draft for review; it is never a Plan."""
    from app.models.planner_draft import PlannerBuildDraft

    require_version_access(db, current_user, project_version_id)
    row = db.query(PlannerBuildDraft).filter(
        PlannerBuildDraft.id == draft_id,
        PlannerBuildDraft.project_version_id == project_version_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Черновик не найден")
    return {
        **draft_summary(row),
        "schedule": row.schedule_json or {},
        "metrics": row.metrics_json or {},
        "rejection": row.rejection_json or {},
        "result_kind": "draft",
        "review_state": "unreviewed",
    }


class BuildTimedOut(TimeoutError):
    """The logical job reached its absolute deadline before publication."""


def _assert_build_is_live(project_version_id: int, deadline_at: str | None) -> None:
    if _cancellation_requested(project_version_id):
        raise BuildCancelled("build cancellation requested")
    if not deadline_at:
        return
    try:
        deadline = datetime.fromisoformat(deadline_at)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise BuildTimedOut("invalid build deadline")
    if datetime.now(timezone.utc) >= deadline:
        raise BuildTimedOut("build deadline reached")


def _infeasible_build_response() -> HTTPException:
    """Expose a stable user action without leaking internal verification data."""
    return HTTPException(
        status_code=422,
        detail="Запрошенные варианты не прошли финальные ограничения. Проверьте кредиты, доказательства LO и настройки программы.",
    )


def _persist_selection_evidence_snapshot(
    db: Session,
    project_version_id: int,
    result: dict,
) -> None:
    """Make publication evidence durable even if a planner implementation omits it.

    The scheduler is expected to attach the snapshot while it creates a
    candidate plan.  Publication has a separate responsibility: it must never
    commit a plan whose later explanation depends on mutable match scores.
    Keeping this guard here makes that invariant survive worker/API version
    skew during a local restart as well as future scheduler refactors.
    """
    plan_id = result.get("plan_id")
    if not plan_id:
        raise RuntimeError("Planner candidate has no durable plan identifier")
    plan = db.query(Plan).filter(Plan.id == int(plan_id)).first()
    if plan is None:
        raise RuntimeError("Planner candidate disappeared before publication")

    metrics = dict(plan.metrics_json or {})
    snapshot = metrics.get("selection_evidence_snapshot")
    if not isinstance(snapshot, dict) or "version" not in snapshot:
        metrics["selection_evidence_snapshot"] = build_selection_evidence_snapshot(
            result.get("schedule") or {}, project_version_id, db
        )
        # JSON columns do not track in-place dictionary changes.  Reassign the
        # full value so SQLAlchemy writes the publication evidence atomically.
        plan.metrics_json = metrics
    result["metrics"] = metrics


def _load_program_spec_for_command(db: Session | None, project_version_id: int) -> tuple[dict, str]:
    """Capture the mutable project state before a job is handed to a worker."""
    if db is None:  # Lightweight router-contract tests do not own a database.
        snapshot = {"schema_version": 1, "project_version_id": int(project_version_id), "test_stub": True}
        return snapshot, program_spec_hash(snapshot)
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if version is None:
        raise HTTPException(status_code=404, detail="Версия проекта не найдена")
    snapshot = build_program_spec_snapshot(version)
    return snapshot, program_spec_hash(snapshot)


def _start_build_heartbeat(project_version_id: int, worker_id: str | None):
    """Keep the durable lease alive while a long planner stage is running."""
    stop_event = threading.Event()
    interval = max(1.0, min(30.0, settings.BUILD_LEASE_SECONDS / 3))
    heartbeat_file = Path(__file__).resolve().parents[3] / ".runtime" / "planner-worker.heartbeat"

    def run():
        heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
        while not stop_event.wait(interval):
            try:
                heartbeat_file.touch()
            except OSError:
                logger.warning("planner heartbeat file update failed", exc_info=True)
            if not _touch_build_lease(project_version_id, worker_id):
                return

    thread = threading.Thread(
        target=run,
        name=f"planner-heartbeat-{project_version_id}",
        daemon=True,
    )
    thread.start()
    return stop_event, thread


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
    if response_payload and response_payload.get("goso_ruleset_version"):
        details["goso_ruleset_version"] = response_payload["goso_ruleset_version"]
    if response_payload and response_payload.get("job_id"):
        details["job_id"] = response_payload["job_id"]
    # A latency number without the actual embedding runtime is not comparable:
    # SBERT, CPU/GPU and deterministic fallback have materially different
    # cost and semantic meaning. Keep this compact and secret-free.
    try:
        from app.kag.embedding_service import embedding_service

        runtime = embedding_service.get_status()
        details["embedding_runtime"] = {
            key: runtime.get(key)
            for key in ("mode", "runtime_profile", "configured_model", "dimension", "device", "model_loaded")
        }
    except Exception:
        details["embedding_runtime"] = {"mode": "unavailable"}
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


@router.post("/{project_version_id}/build", response_model=PlannerBuildResponse | PlannerBuildQueuedResponse, dependencies=[Depends(require_permission("planner", "write"))])
def build_plan(
    project_version_id: int,
    payload: PlannerBuildRequest = Body(default_factory=PlannerBuildRequest),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Build all three curriculum plan variants"""
    request_hash = _build_request_hash(project_version_id, payload.variants)
    program_spec_json, spec_hash = _load_program_spec_for_command(db, project_version_id)
    if settings.ASYNC_BUILDS and os.environ.get("CURRICULUM_KAG_WORKER") != "1":
        previous_status = _get_build_status(project_version_id)
        if (
            idempotency_key
            and previous_status.get("idempotency_key") == idempotency_key
            and previous_status.get("request_hash")
            and previous_status.get("request_hash") != request_hash
        ):
            raise HTTPException(status_code=409, detail="Idempotency-Key уже использован для другого запроса")
        if (
            idempotency_key
            and previous_status.get("idempotency_key") == idempotency_key
            and previous_status.get("request_hash") == request_hash
            and previous_status.get("state") not in {None, "idle"}
        ):
            replay_state = previous_status.get("state")
            return JSONResponse(status_code=200 if replay_state in {"complete", "failed", "rejected", "cancelled", "timed_out"} else 202, content={
                "state": replay_state,
                "job_id": previous_status.get("job_id"),
                "project_version_id": project_version_id,
                "status_url": f"/api/planner/{project_version_id}/build-status",
                "idempotent_replay": True,
            })
        queued = _claim_build_status(
            project_version_id,
            job_id=f"build-{os.urandom(16).hex()}",
            request_hash=request_hash,
            program_spec_json=program_spec_json,
            program_spec_hash=spec_hash,
            requested_by_user_id=current_user.id,
            # Keep the command itself in the durable status snapshot.  A
            # persistent worker must be able to recover a queued job after an
            # API/worker restart without reconstructing the request from an
            # OS process command line.
            requested_variants=payload.variants,
            state="queued",
            stage="queued",
            progress=0,
            started_at=None,
            elapsed_seconds=0,
            idempotency_key=idempotency_key,
        )
        if queued is None:
            raise HTTPException(status_code=409, detail="Построение вариантов уже выполняется")
        worker_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "run_planner_build_worker.py"))
        command = [
            sys.executable,
            worker_script,
            "--version-id", str(project_version_id),
            "--user-id", str(current_user.id),
            "--variants", json.dumps(payload.variants, ensure_ascii=False),
            "--job-id", queued["job_id"],
        ]
        if idempotency_key:
            command.extend(["--idempotency-key", idempotency_key])
        # In production a dedicated daemon owns the queue.  The legacy
        # one-shot process remains available only when no daemon is deployed.
        if settings.PERSISTENT_PLANNER_WORKER:
            return JSONResponse(status_code=202, content={
                "state": "queued",
                "job_id": queued["job_id"],
                "project_version_id": project_version_id,
                "status_url": f"/api/planner/{project_version_id}/build-status",
            })
        try:
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            worker_env = os.environ.copy()
            worker_env["CURRICULUM_KAG_WORKER"] = "1"
            process = subprocess.Popen(
                command,
                cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
                env=worker_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creation_flags,
            )
        except OSError as exc:
            _replace_build_status(project_version_id, state="failed", stage="failed", progress=0, error="Не удалось запустить worker построения")
            logger.exception("Could not start planner worker for version %s", project_version_id)
            raise HTTPException(status_code=503, detail="Не удалось запустить worker построения") from exc
        return JSONResponse(status_code=202, content={
            "state": "queued",
            "job_id": queued["job_id"],
            "project_version_id": project_version_id,
            "status_url": f"/api/planner/{project_version_id}/build-status",
        })
    build_started = time.perf_counter()
    sql_measurement = start_sql_query_measurement()
    sql_query_count: int | None = None
    stage_started = build_started
    timings = {}
    previous_status = _get_build_status(project_version_id)
    expected_job_id = os.environ.get("CURRICULUM_KAG_EXPECTED_JOB_ID")
    if expected_job_id and previous_status.get("job_id") != expected_job_id:
        raise HTTPException(status_code=409, detail="Очередь этого построения уже была отменена или заменена")
    if (
        idempotency_key
        and previous_status.get("idempotency_key") == idempotency_key
        and previous_status.get("request_hash")
        and previous_status.get("request_hash") != request_hash
    ):
        raise HTTPException(status_code=409, detail="Idempotency-Key уже использован для другого запроса")
    if (
        idempotency_key
        and previous_status.get("state") == "complete"
        and previous_status.get("idempotency_key") == idempotency_key
    ):
        return JSONResponse(status_code=200, content={
            "state": "complete",
            "job_id": previous_status.get("job_id"),
            "project_version_id": project_version_id,
            "status_url": f"/api/planner/{project_version_id}/build-status",
            "idempotent_replay": True,
        })
    claimed = _claim_build_status(
        project_version_id,
        # The detached worker promotes the API-created queued job.  It must
        # retain that public identity while receiving a new *worker* owner.
        job_id=previous_status.get("job_id") or f"build-{os.urandom(16).hex()}",
        request_hash=request_hash,
        program_spec_json=previous_status.get("program_spec_json") or program_spec_json,
        program_spec_hash=previous_status.get("program_spec_hash") or spec_hash,
        requested_by_user_id=current_user.id,
        _expected_job_id=expected_job_id,
        state="running",
        stage="matching",
        progress=5,
        started_at=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=0,
        timings=timings,
        idempotency_key=idempotency_key,
    )
    if claimed is None:
        raise HTTPException(status_code=409, detail="Построение вариантов уже выполняется")
    heartbeat_stop, heartbeat_thread = _start_build_heartbeat(
        project_version_id, (claimed or {}).get("worker_id")
    )
    deadline_at = (claimed or {}).get("deadline_at")
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
        _assert_build_is_live(project_version_id, deadline_at)
        expected_spec_hash = str((claimed or {}).get("program_spec_hash") or "")
        if expected_spec_hash and program_spec_hash(build_program_spec_snapshot(version)) != expected_spec_hash:
            raise BuildInfeasible("ProgramSpec changed after this build was queued")
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
            _assert_build_is_live(project_version_id, deadline_at)
            _set_build_status(project_version_id, **payload)
        scoring_signature = scoring_input_signature(version, db, epvo_signature=epvo_signature)
        scoring_cached = cache_hit(db, version, SCORING_CACHE_ACTION, scoring_signature)
        if not scoring_cached:
            scoring_result = compute_all_matches(project_version_id, db, progress_callback=update_scoring_progress)
            # Persist exactly the signature used for the cache lookup. A
            # second recomputation without the EPVO fingerprint made every
            # retry miss scoring cache even when inputs were unchanged.
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

        requested_variants = normalize_requested_variants(payload.variants)
        if not requested_variants:
            raise HTTPException(status_code=422, detail="Выберите хотя бы один вариант плана: A, B или C")

        def build_variant(variant_type: str) -> dict:
            # B/C solve the same hard model with an explicit no-good cut
            # against A's real-course set; they never clone A's schedule.
            reference: frozenset[int] | None = None
            if variant_type in {"B", "C"}:
                current_a = variants.get("A")
                if current_a:
                    reference = frozenset(
                        int(item["course_id"])
                        for items in (current_a.get("schedule") or {}).values()
                        for item in items if item.get("course_id") is not None
                    )
                else:
                    previous_a = max(
                        (plan for plan in old_plans if plan.variant_type == "A"),
                        key=lambda plan: plan.id, default=None,
                    )
                    if previous_a is not None:
                        reference = frozenset(
                            int(row.course_id)
                            for row in db.query(PlanItem).filter(
                                PlanItem.plan_id == previous_a.id,
                                PlanItem.course_id.is_not(None),
                            ).all()
                        )
                if not reference:
                    raise PlanningFailure("missing_variant_a_reference", {
                        "variant": variant_type,
                        "message": "Сначала постройте вариант A или запросите A вместе с альтернативами.",
                    })
            other_references = ()
            if variant_type == "C" and variants.get("B"):
                other_references = (frozenset(
                    int(item["course_id"])
                    for items in (variants["B"].get("schedule") or {}).values()
                    for item in items if item.get("course_id") is not None
                ),)
            return build_curriculum_plan(
                project_version_id,
                db,
                variant_type,
                commit=False,
                diversity_reference=reference,
                diversity_references=other_references,
            )

        variants: dict[str, dict] = {}

        def set_variant_stage(stage: str, progress: int) -> None:
            _set_build_status(
                project_version_id,
                stage=stage,
                progress=progress,
                elapsed_seconds=round(time.perf_counter() - build_started, 1),
                timings=dict(timings),
            )

        variants, variant_timings = run_requested_variants(
            requested_variants,
            build_variant=build_variant,
            assert_live=lambda: _assert_build_is_live(project_version_id, deadline_at),
            set_stage=set_variant_stage,
            stage_progress={"A": 25, "B": 50, "C": 75},
            completed_progress={"A": 40, "B": 65, "C": 85},
            results=variants,
        )
        timings.update(variant_timings)

        # The plan rows are already flushed by the scheduler but are not yet
        # committed.  Freeze their selection evidence at this single
        # publication boundary before feasibility filtering and activation.
        for result in variants.values():
            _persist_selection_evidence_snapshot(db, project_version_id, result)

        rejected_variants = []
        # A/B/C are alternatives, not cosmetic labels.  Reject a build that
        # accidentally persisted the same course/bridge sequence twice; the
        # caller can then request fewer variants or adjust the constraints.
        signatures = {}
        for name, row in variants.items():
            signatures.setdefault(schedule_fingerprint(row.get("schedule") or {}), []).append(name)
        duplicate_variants = {
            duplicate_name: duplicate_names
            for duplicate_names in signatures.values()
            if len(duplicate_names) > 1
            for duplicate_name in duplicate_names[1:]
        }
        for variant_name, result in variants.items():
            verification = result.get("verification") or {}
            duplicate_names = duplicate_variants.get(variant_name)
            # Quality warnings are review guidance, not a generation failure.
            # Only hard feasibility violations may prevent replacing the old
            # plans; otherwise a valid plan could never be saved when one
            # advisory international-quality check is below its threshold.
            # Regulatory KZ plans may retain advisory quality warnings, but
            # no jurisdiction may bypass a hard feasibility failure or a
            # programme LO without real-course evidence.
            if duplicate_names or must_reject_variant(verification):
                hard_details = []
                if duplicate_names:
                    hard_details.append({
                        "reason": "variant_not_distinct",
                        "variants": duplicate_names,
                    })
                for key, label in (
                    ("prerequisite_violations", "prerequisites"),
                    ("semester_load_violations", "semester_load"),
                    ("credit_violations", "credits"),
                    ("domain_quota_violations", "domain_quota"),
                    ("course_lo_violations", "course_lo"),
                    ("bridge_module_overflow", "bridge_limit"),
                ):
                    value = verification.get(key)
                    count = len(value) if isinstance(value, list) else int(value or 0)
                    if count:
                        hard_details.append({"reason": label, "count": count})
                for item in (verification.get("goso_compliance") or {}).get("violations") or []:
                    hard_details.append({"reason": item.get("reason", "goso"), "details": item})
                hard_details.append({
                    "reason": "verifier_breakdown",
                    "quality_reasons": sorted(
                        str(item.get("reason"))
                        for item in (verification.get("quality_violations") or [])
                        if isinstance(item, dict) and item.get("reason")
                    ),
                    "counts": {
                        "prerequisites": len(verification.get("prerequisite_violations") or []),
                        "semester_load": len(verification.get("semester_load_violations") or []),
                        "credits": len(verification.get("credit_violations") or []),
                        "domain_quota": len(verification.get("domain_quota_violations") or []),
                        "goso": len((verification.get("goso_compliance") or {}).get("violations") or []),
                        "course_lo": int(verification.get("course_lo_violations") or 0),
                        "real_lo": len(verification.get("lo_without_real_course") or []),
                        "bridge_overflow": int(verification.get("bridge_module_overflow") or 0),
                    },
                    "actual": {
                        "total_credits": verification.get("total_credits"),
                        "target_credits": verification.get("target_credits"),
                        "semester_loads": verification.get("semester_loads"),
                        "domain_credits": verification.get("domain_credits"),
                        "lo_coverage": verification.get("min_lo_coverage"),
                        "bridge_modules": verification.get("bridge_module_count"),
                    },
                    "missing_real_lo": [
                        {
                            "lo_code": item.get("lo_code"),
                            "max_real_course_score": item.get("max_real_course_score"),
                            "bridge_supported": bool(item.get("bridge_supported")),
                        }
                        for item in (verification.get("lo_without_real_course") or [])[:20]
                    ],
                })
                quality_violations = list(verification.get("quality_violations") or [])
                if duplicate_names:
                    quality_violations.append({
                        "reason": "variant_not_distinct",
                        "variants": duplicate_names,
                    })
                rejected_variants.append({
                    "variant": variant_name,
                    "hard": int(verification.get("hard_violation_count") or 0),
                    "hard_details": hard_details,
                    "quality_violations": quality_violations,
                })
        publishable_variants, rejected_variant_names = partition_publishable_variants(
            variants, rejected_variants,
        )
        draft_payloads = build_rejected_draft_payloads(
            variants,
            rejected_variants,
            job_id=(claimed or {}).get("job_id"),
        )
        # A methodist can ask for A/B/C as a comparison, but an invalid
        # alternative must not discard a sound published A.  Keep the safety
        # boundary strict: only variants with zero hard violations are saved.
        # If every requested variant fails, preserve the existing plans and
        # return the same infeasible result as before.
        if rejected_variants and not publishable_variants:
            summary = "; ".join(
                f"{row['variant']}: hard={row['hard']}, quality={len(row['quality_violations'])}"
                + (f", details={row['hard_details']}" if row.get("hard_details") else "")
                for row in rejected_variants
            )
            raise BuildInfeasible(
                "Новые варианты не прошли финальную проверку; старые планы сохранены. "
                + summary,
                details=rejected_variants,
                drafts=draft_payloads,
            )

        # Retain rejected comparison variants as isolated working drafts.
        # They are never inserted into Plan and therefore cannot become active.
        persisted_drafts = persist_rejected_drafts(
            db,
            project_version_id=project_version_id,
            created_by_user_id=current_user.id,
            payloads=draft_payloads,
        )
        draft_summaries = [draft_summary(row) for row in persisted_drafts]

        # build_curriculum_plan uses the surrounding transaction.  Remove
        # invalid candidates before committing, otherwise a rejected B/C could
        # become visible merely because A was valid in the same request.
        for variant_name in rejected_variant_names:
            plan_id = variants.get(variant_name, {}).get("plan_id")
            if plan_id:
                rejected_plan = db.query(Plan).filter(Plan.id == plan_id).first()
                if rejected_plan:
                    db.delete(rejected_plan)
        variants = publishable_variants

        stage_started = time.perf_counter()
        _assert_build_is_live(project_version_id, deadline_at)
        _set_build_status(
            project_version_id, stage="saving", progress=92,
            elapsed_seconds=round(time.perf_counter() - build_started, 1), timings=dict(timings),
        )
        # A partial build (for example only A) must not destroy the variants
        # that were intentionally kept (B/C). Replace only variants that are
        # both requested and verified, so a rejected B/C also preserves its
        # last known version for comparison.
        for old_plan in old_plans:
            if old_plan.variant_type in variants:
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
        _assert_build_is_live(project_version_id, deadline_at)
        db.commit()
        timings["saving"] = round(time.perf_counter() - stage_started, 2)
        _replace_build_status(project_version_id, **{
            "state": "complete",
            "stage": "complete",
            "progress": 100,
            "change_report": change_report,
            "active_variant": best_variant,
            "publication_status": "partial" if rejected_variants else "complete",
            "rejected_variants": rejected_variants,
            "drafts": draft_summaries,
            "elapsed_seconds": round(time.perf_counter() - build_started, 1),
            "timings": timings,
        })

        response_payload = {
            "variants": variants,
            "active_variant": best_variant,
            "goso_ruleset_version": (
                ((variants.get(best_variant, {}).get("metrics") or {}).get("goso_ruleset_version"))
                if best_variant else None
            ),
            "job_id": (claimed or {}).get("job_id"),
            "epvo_repository": epvo_sync,
            "change_report": change_report,
            "publication_status": "partial" if rejected_variants else "complete",
            "rejected_variants": rejected_variants,
            "drafts": draft_summaries,
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
    except BuildCancelled:
        if sql_query_count is None:
            sql_query_count = finish_sql_query_measurement(sql_measurement)
        db.rollback()
        _replace_build_status(project_version_id, state="cancelled", stage="cancelled", progress=0, error="Построение отменено пользователем", timings=timings)
        raise HTTPException(status_code=409, detail="Построение отменено пользователем")
    except BuildInfeasible as exc:
        if sql_query_count is None:
            sql_query_count = finish_sql_query_measurement(sql_measurement)
        db.rollback()
        persisted_drafts = []
        if exc.drafts:
            try:
                persisted_drafts = persist_rejected_drafts(
                    db,
                    project_version_id=project_version_id,
                    created_by_user_id=current_user.id,
                    payloads=exc.drafts,
                )
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Could not persist rejected planner drafts for version %s", project_version_id)
        rejection_details = [
            {
                "variant": item.get("variant"),
                "hard": int(item.get("hard") or 0),
                "hard_details": item.get("hard_details") or [],
                "quality_reasons": [
                    value.get("reason") for value in (item.get("quality_violations") or [])
                    if isinstance(value, dict) and value.get("reason")
                ],
            }
            for item in getattr(exc, "details", [])
            if isinstance(item, dict)
        ][:3]
        _replace_build_status(project_version_id, **{
            "state": "rejected", "stage": "infeasible", "progress": 0,
            # Keep the actionable, non-sensitive verifier summary in the
            # durable status.  The HTTP response remains the generic safe
            # 422 below; this text is for the authenticated owner’s status
            # page and contains no traceback or model prompt.
            "error": str(exc)[:2000] or "Финальная проверка вариантов выявила невыполнимые ограничения.",
            "verification_summary": rejection_details,
            "drafts": [draft_summary(row) for row in persisted_drafts],
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
            response_payload={"verification_summary": rejection_details},
        )
        raise _infeasible_build_response()
    except BuildTimedOut:
        if sql_query_count is None:
            sql_query_count = finish_sql_query_measurement(sql_measurement)
        db.rollback()
        _replace_build_status(project_version_id, **{
            "state": "timed_out", "stage": "timed_out", "progress": 0,
            "error": "Построение превысило допустимое время до публикации результата.",
            "elapsed_seconds": round(time.perf_counter() - build_started, 1),
            "timings": timings,
        })
        _record_build_telemetry(
            db, current_user=current_user, project_version_id=project_version_id,
            state="timed_out", elapsed_seconds=time.perf_counter() - build_started,
            timings=timings, sql_query_count=sql_query_count,
        )
        raise HTTPException(status_code=504, detail="Построение превысило допустимое время; повторите запрос после проверки ограничений")
    except PlanningFailure as exc:
        if sql_query_count is None:
            sql_query_count = finish_sql_query_measurement(sql_measurement)
        db.rollback()
        timed_out = exc.status in {"solver_timeout", "solver_limit"}
        messages = {
            "solver_timeout": "Оптимизатор достиг лимита времени; старый план сохранён.",
            "solver_limit": "Оптимизатор достиг лимита поиска; старый план сохранён.",
            "no_solution_in_bounded_frontier": "В проверенном наборе дисциплин допустимый план не найден; старый план сохранён.",
            "infeasible_with_complete_frontier": "При текущих дисциплинах и обязательных требованиях допустимый план не найден.",
            "verifier_rejected": "Найденные варианты не прошли независимую проверку; старый план сохранён.",
            "missing_variant_a_reference": "Для альтернативы сначала нужен вариант A.",
            "invalid_candidate_data": "В каталоге обнаружены некорректные данные дисциплин или пререквизитов.",
        }
        message = messages.get(exc.status, "План не прошёл проверку; старый вариант сохранён.")
        _replace_build_status(project_version_id, **{
            "state": "timed_out" if timed_out else "rejected",
            "stage": exc.status, "progress": 0, "error": message,
            "verification_summary": [{"status": exc.status, "details": exc.details}],
            "elapsed_seconds": round(time.perf_counter() - build_started, 1),
            "timings": timings,
        })
        _record_build_telemetry(
            db, current_user=current_user, project_version_id=project_version_id,
            state="timed_out" if timed_out else "rejected",
            elapsed_seconds=time.perf_counter() - build_started,
            timings=timings, sql_query_count=sql_query_count,
            response_payload={"planner_status": exc.status},
        )
        raise HTTPException(status_code=504 if timed_out else 422, detail=message)
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
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=max(1.0, min(5.0, settings.BUILD_LEASE_SECONDS / 4)))


@router.post("/{project_version_id}/build-retry", response_model=PlannerBuildResponse | PlannerBuildQueuedResponse, dependencies=[Depends(require_permission("planner", "write"))])
def retry_build(
    project_version_id: int,
    payload: PlannerBuildRequest = Body(default_factory=PlannerBuildRequest),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Retry only a terminal build; never interrupt a live attempt."""
    status = _get_build_status(project_version_id)
    if status.get("state") in {"queued", "running", "cancellation_requested"}:
        raise HTTPException(status_code=409, detail="Текущее построение ещё выполняется")
    if status.get("state") not in {"failed", "timed_out", "cancelled", "rejected"}:
        raise HTTPException(status_code=409, detail="Для этой версии нет неуспешного построения для повтора")
    return build_plan(
        project_version_id=project_version_id,
        payload=payload,
        db=db,
        current_user=current_user,
        idempotency_key=idempotency_key,
    )


@router.get("/{project_version_id}/build-status", response_model=PlannerBuildStatusResponse)
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


@router.post("/{project_version_id}/build-cancel", response_model=PlannerBuildCancelResponse, dependencies=[Depends(require_permission("planner", "write"))])
def cancel_build(
    project_version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel a queued build immediately or request cancellation while running."""
    status = _get_build_status(project_version_id)
    if status.get("state") not in {"queued", "running"}:
        return {"state": status.get("state", "idle"), "cancelled": False}
    status = _request_build_cancel(project_version_id)
    requested_state = "cancellation_requested" if status.get("state") == "running" else "cancelled"
    return {"state": requested_state, "cancelled": True, "updated_at": status.get("updated_at")}


@router.get("/{project_version_id}/performance", response_model=PlannerBuildPerformanceResponse)
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
    duration_p95 = _percentile(durations, 0.95)
    return {
        "sample_size": len(entries),
        "duration_ms": {"p50": _percentile(durations, 0.5), "p95": duration_p95},
        "sql_query_count": {"p50": _percentile(query_counts, 0.5), "p95": _percentile(query_counts, 0.95)},
        "response_bytes": {"p50": _percentile(response_sizes, 0.5), "p95": _percentile(response_sizes, 0.95)},
        "cache_hit_rate": round(sum(cache_rates) / len(cache_rates), 3) if cache_rates else None,
        "p95_budget_ms": settings.PLANNER_P95_BUDGET_MS,
        "p95_within_budget": None if not durations else duration_p95 <= settings.PLANNER_P95_BUDGET_MS,
        "recent": entries[:10],
    }


@router.get("/observability/summary", response_model=PlannerObservabilityResponse, dependencies=[Depends(require_permission("planner", "read"))])
def get_planner_observability_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return aggregate planner signals without exposing plan or user payloads."""
    statuses = db.query(PlanBuildStatus.state).all()
    state_counts: dict[str, int] = {}
    for (state,) in statuses:
        key = str(state or "unknown")
        state_counts[key] = state_counts.get(key, 0) + 1
    now = datetime.now(timezone.utc)
    active_leases = db.query(PlanBuildStatus).filter(
        PlanBuildStatus.lease_expires_at.is_not(None),
        PlanBuildStatus.lease_expires_at > now,
        PlanBuildStatus.state.in_(["queued", "running"]),
    ).count()
    rows = (
        db.query(AuditEvent.details_json)
        .filter(AuditEvent.action == "planner_build_telemetry")
        .order_by(AuditEvent.timestamp.desc())
        .limit(1000)
        .all()
    )
    durations = [float(details.get("duration_ms") or 0) for (details,) in rows if isinstance(details, dict)]
    p95 = _percentile(durations, 0.95)
    return {
        "build_states": state_counts,
        "failed_or_timed_out": state_counts.get("failed", 0) + state_counts.get("timed_out", 0),
        "active_leases": active_leases,
        "telemetry_sample_size": len(durations),
        "duration_ms": {"p50": _percentile(durations, 0.5), "p95": p95},
        "p95_budget_ms": settings.PLANNER_P95_BUDGET_MS,
        "p95_within_budget": None if not durations else p95 <= settings.PLANNER_P95_BUDGET_MS,
    }


@router.post("/{project_version_id}/recompute-matches", dependencies=[Depends(require_permission("planner", "write"))])
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




@router.post("/{plan_id}/toggle-active", dependencies=[Depends(require_permission("planner", "write"))])
async def toggle_plan_active(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _plan_owner: User = Depends(require_plan_object_access),
):
    """Toggle a plan as active and deactivate others for the same project version"""
    from app.models.plan import Plan

    plan = require_plan_access(db, current_user, plan_id)
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
