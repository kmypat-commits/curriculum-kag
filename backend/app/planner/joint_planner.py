"""Verified joint schedule assembly; no publication or transaction commit."""

from __future__ import annotations

import hashlib
import json
import time

from sqlalchemy.orm import Session

from app.models.project import ProjectVersion
from app.planner.admission import audit_final_course_admission
from app.planner.course_policy import course_curriculum_role, project_domain_terms
from app.planner.final_schedule_checks import audit_final_schedule_boundary
from app.planner.joint_contract import PlanningFailure
from app.planner.joint_frontier import build_joint_frontier
from app.planner.joint_solver import solve_joint
from app.planner.scheduler_domain_rules import course_domain_matches
from app.planner.verifier import verify_curriculum_plan


FRONTIER_LIMITS = (120, 240, 480)
MAX_VERIFIER_ATTEMPTS_PER_FRONTIER = 3
SOLVER_TIME_LIMIT_SECONDS = 30.0


def _schedule_fingerprint(schedule: dict[int, list[dict]]) -> str:
    rows = [
        (int(semester), int(item.get("course_id") or 0),
         int(item.get("bridge_module_id") or 0), int(item.get("credits") or 0))
        for semester, items in schedule.items() for item in items
    ]
    encoded = json.dumps(sorted(rows), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _frontier_fingerprint(problem) -> str:
    payload = {
        "candidates": [
            (candidate.course_id, int(candidate.item.get("credits") or 0),
             candidate.allowed_semesters, candidate.prerequisites,
             sorted(candidate.lo_scores.items()), candidate.domain_shares)
            for candidate in getattr(problem, "candidates", ())
        ],
        "fixed": [
            (semester, item.get("course_id"), item.get("credits"))
            for semester, items in sorted(getattr(problem, "fixed_schedule", {}).items())
            for item in items
        ],
        "target": getattr(problem, "target_credits", None),
        "domain_minima": getattr(problem, "domain_minima", ()),
    }
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str,
    ).encode("utf-8")).hexdigest()


def build_verified_joint_schedule(
    version: ProjectVersion,
    db: Session,
    variant_type: str,
    forbidden_sets: tuple[frozenset[int], ...] = (),
) -> tuple[dict[int, list[dict]], dict]:
    """Return only a schedule passing both admission and independent verifier.

    Infeasibility from a truncated frontier triggers deterministic widening;
    verifier disagreement triggers a bounded no-good retry. No plan is saved.
    """
    started = time.perf_counter()
    if variant_type not in {"A", "B", "C"}:
        raise ValueError("variant_type must be A, B or C")
    rejected: list[dict] = []
    attempts: list[dict] = []
    last_failure: PlanningFailure | None = None
    last_frontier_hash = ""
    for limit in FRONTIER_LIMITS:
        frontier_started = time.perf_counter()
        problem = build_joint_frontier(version, db, limit=limit)
        frontier_seconds = time.perf_counter() - frontier_started
        last_frontier_hash = _frontier_fingerprint(problem)
        rejected_placements: list[frozenset[tuple[int, int]]] = []
        for _attempt in range(MAX_VERIFIER_ATTEMPTS_PER_FRONTIER):
            try:
                result = solve_joint(
                    problem, time_limit_seconds=SOLVER_TIME_LIMIT_SECONDS,
                    forbidden_sets=forbidden_sets,
                    forbidden_placements=tuple(rejected_placements),
                )
            except PlanningFailure as failure:
                last_failure = failure
                attempts.append({"frontier_hash": last_frontier_hash,
                                 "limit": limit, "solver_status": failure.status,
                                 "details": failure.details})
                break
            schedule = result.schedule
            excluded_course_ids = {
                int(value)
                for value in (version.project.constraints_json or {}).get("excluded_course_ids", ())
                if str(value).isdigit()
            }
            selected_excluded = sorted({
                int(item["course_id"])
                for items in schedule.values() for item in items
                if item.get("course_id") is not None
                and int(item["course_id"]) in excluded_course_ids
            })
            if selected_excluded:
                raise PlanningFailure("excluded_course_selected", {
                    "course_ids": selected_excluded, "variant": variant_type,
                })
            fingerprint = _schedule_fingerprint(schedule)
            attempt = {
                "frontier_hash": last_frontier_hash, "limit": limit,
                "solver_status": "optimal" if result.optimality_proven else "feasible_at_limit",
                "solver_seconds": result.solver_seconds,
                "schedule_fingerprint": fingerprint,
            }
            placement = frozenset(
                (int(item["course_id"]), int(semester))
                for semester, items in schedule.items() for item in items
                if item.get("course_id") in result.selected_course_ids
            )
            admission = audit_final_course_admission(schedule, version, db)
            if not admission["passed"]:
                attempts.append({**attempt, "boundary_status": "admission_rejected"})
                rejected.append({
                    "fingerprint": fingerprint, "reason": "admission",
                    "details": admission["violations"][:12],
                })
                rejected_placements.append(placement)
                continue
            verification = verify_curriculum_plan(schedule, version, db)
            if not verification.get("feasible") or not verification.get("quality_passed"):
                attempts.append({
                    **attempt, "boundary_status": "verifier_rejected",
                    "hard": verification.get("hard_violation_count"),
                    "quality": verification.get("quality_violations", [])[:12],
                })
                rejected.append({
                    "fingerprint": fingerprint, "reason": "verifier",
                    "hard": verification.get("hard_violation_count"),
                    "quality": verification.get("quality_violations", [])[:12],
                })
                rejected_placements.append(placement)
                continue
            domains = project_domain_terms(version, db)
            boundary = audit_final_schedule_boundary(
                schedule, db=db, project_version=version,
                project_domains=domains,
                declared_secondary_domain=str(version.project.domain2 or "").casefold(),
                is_project_domain=lambda course: course_domain_matches(course, domains),
                is_general_course=lambda course: course_curriculum_role(course, domains) == "general",
            )
            if boundary["invalid_domain_courses"] or not boundary["admission"]["passed"]:
                attempts.append({**attempt, "boundary_status": "domain_rejected"})
                rejected.append({
                    "fingerprint": fingerprint, "reason": "boundary",
                    "invalid_domain_courses": boundary["invalid_domain_courses"][:12],
                    "admission": boundary["admission"]["violations"][:12],
                })
                rejected_placements.append(placement)
                continue
            return schedule, {
                "verification": verification,
                "boundary": boundary,
                "planner": {
                    "name": "joint_milp",
                    "variant": variant_type,
                    "frontier_limit": limit,
                    "frontier_count": len(getattr(problem, "candidates", ())),
                    "frontier_hash": last_frontier_hash,
                    "frontier_truncated": problem.frontier_truncated,
                    "frontier_exclusions": problem.exclusions,
                    "frontier_seconds": round(frontier_seconds, 3),
                    "solver_seconds": round(result.solver_seconds, 3),
                    "total_seconds": round(time.perf_counter() - started, 3),
                    "objective": result.objective,
                    "optimality_proven": result.optimality_proven,
                    "fingerprint": fingerprint,
                    "selected_course_ids": sorted(result.selected_course_ids),
                    "attempts": attempts + [{**attempt, "boundary_status": "accepted"}],
                },
            }
        if last_failure and last_failure.status in {
            "solver_timeout", "solver_limit", "solver_error", "invalid_candidate_data",
        }:
            raise last_failure
        if not problem.frontier_truncated:
            break
    if rejected:
        raise PlanningFailure("verifier_rejected", {
            "rejected": rejected[-12:], "count": len(rejected),
            "last_solver_status": last_failure.status if last_failure else None,
            "frontier_hash": last_frontier_hash, "attempts": attempts,
        })
    if last_failure:
        raise PlanningFailure(last_failure.status, {
            **last_failure.details, "frontier_hash": last_frontier_hash,
            "attempts": attempts,
        })
    raise PlanningFailure("no_solution_in_bounded_frontier", {
        "reason": "search_exhausted", "frontier_limits": FRONTIER_LIMITS,
    })
