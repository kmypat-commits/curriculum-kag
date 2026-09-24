from __future__ import annotations

import time
from functools import partial
from typing import Dict, List
from itertools import combinations
import math
import re
from statistics import median
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models.bridge_module import BridgeModule
from app.models.course import Course, course_prerequisites
from app.models.embedding import MatchScore
from app.models.project import LearningOutcome, ProjectVersion
from app.models.epvo import EpvoDirection, EpvoDisciplineLoLink, EpvoDisciplineNormalized, EpvoGroup
from app.services.epvo_repository import epvo_row_matches_education_level, epvo_row_relevance_score
from app.planner.verifier import (
    TOTAL_CREDIT_TOLERANCE,
    _ict_competency_audit,
    _ict_competency_requirements,
    verify_curriculum_plan,
)
from app.planner.goso import merge_goso_items
from app.planner.scheduler_utils import move_item as _move_item
from app.planner.scheduler_utils import remove_item_once as _remove_item_once
from app.planner.scheduler_utils import swap_items as _swap_items
from app.planner.scheduler_utils import schedule_loads as _schedule_loads
from app.planner.scheduler_utils import semester_by_course as _semester_by_course
from app.planner.scheduler_utils import course_dependents as _course_dependents
from app.planner.scheduler_utils import title_key as _title_key
from app.planner.scheduler_admission_evidence import sanitize_admitted_course_items
from app.planner.scheduler_text import has_domain_term as _has_domain_term
from app.planner.scheduler_text import short_lo_theme as _short_lo_theme
from app.planner.prerequisite_inference import (
    infer_schedule_prerequisites as _infer_schedule_prerequisites,
)
from app.planner.plan_metrics import calculate_plan_metrics
from app.planner.course_selection import (
    _bridge_item,
    _diversify_variant_items,
    _ensure_foundation_capacity,
    _fill_existing_bridge_credit_gap,
    _fit_real_professional_block_after_goso,
    _force_bridge_item,
    _limit_general_course_items,
    _normalize_selected_courses_for_quality,
    _promote_epvo_priority_courses,
    _remap_equivalent_prerequisites,
    _repair_missing_ict_competencies,
    _select_exact_professional_subset,
    _trim_to_target_credits,
    ensure_credit_bridge_modules,
    ensure_core_interdisciplinary_bridge,
    ensure_secondary_domain_bridge_modules,
    select_courses_for_variant,
)
from app.planner.timing import PlannerTimer
from app.planner.bridge_policy import bridge_module_limit
from app.planner.bridge_budget import cap_bridge_items_to_budget as _cap_bridge_items_to_budget
from app.planner.schedule_credit_gap import fill_schedule_credit_gap as _fill_schedule_credit_gap
from app.planner.exact_credit_repair import repair_exact_real_credit_overage
from app.planner.domain_evidence import domain_label_matches
from app.planner.credit_balancing import (
    _rebalance_semester_load,
    _relocate_bounded_bridges,
    _repair_underloaded_semesters_with_bridges,
    _shift_excess_load_to_balance_modules,
    _strict_rebalance_max_load,
    _trim_schedule_to_target_credits,
)
from app.planner.semester_repair import (
    _apply_scoped_epvo_semesters,
    _repair_final_admission_misplacements,
    _repair_final_domain_quotas,
    _repair_semester_appropriateness,
)
from app.planner.invariant_ledger import InvariantLedger
from app.planner.course_scheduling import schedule_courses
from app.planner.scheduler_domain_rules import (
    course_domain_matches as _course_domain_matches,
    find_invalid_project_domain_courses as _find_invalid_project_domain_courses,
    has_foreign_professional_title as _has_foreign_professional_title,
    is_interdisciplinary_title_relevant as _is_interdisciplinary_title_relevant,
    is_it_medicine_support_course as _is_it_medicine_support_course,
    invalid_project_domain_label as _is_invalid_project_domain_label,
)

from app.planner.scheduler_catalogue import (
    foundation_equivalent_title_key as _foundation_equivalent_title_key,
    is_component_placeholder_title as _is_component_placeholder_title,
    unique_items_by_title as _unique_items_by_title,
)

from app.planner.course_policy import (
    course_curriculum_role as _course_curriculum_role,
    course_role_rank as _course_role_rank,
    education_level_course_allowed as _education_level_course_allowed,
    project_domain_terms as _project_domain_terms,
)
from app.planner.course_admission_policy import is_course_in_project_domain as _is_course_in_project_domain
from app.planner.admission import (
    audit_final_course_admission as _audit_final_course_admission,
    credible_professional_lo_by_course as _credible_professional_lo_by_course,
    minimum_appropriate_semester as _minimum_appropriate_semester,
)
from app.planner.final_schedule_checks import audit_final_schedule_boundary, late_schedule_snapshot
from app.planner.selection_evidence import build_selection_evidence_snapshot
from app.planner.plan_result_assembly import persist_plan_result


# Canonical implementations live in the pure semester-rules module.  The
# aliases keep existing internal callers and external audit scripts stable.
from app.planner.semester_rules import (
    complexity_min_semester as _complexity_min_semester,
    cycle_min_semester as _cycle_min_semester,
    foundation_max_semester as _foundation_max_semester,
    late_stage_min_semester as _late_stage_min_semester,
    minimum_appropriate_semester as _item_minimum_appropriate_semester,
)














































def build_curriculum_plan(
    project_version_id: int,
    db: Session,
    variant_type: str = "A",
    commit: bool = True,
    selection_variant_type: str | None = None,
    selected_courses_override: List[Dict] | None = None,
) -> Dict:
    trace = PlannerTimer(f"[planner-timing] variant={variant_type}").trace

    project_version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not project_version:
        raise ValueError(f"Project version {project_version_id} not found")
    constraints = project_version.project.constraints_json or {}
    excluded_course_ids = {
        int(value) for value in (constraints.get("excluded_course_ids") or [])
        if str(value).isdigit()
    }
    selected_courses = (
        [dict(item) for item in selected_courses_override]
        if selected_courses_override is not None
        else select_courses_for_variant(
            project_version_id,
            db,
            selection_variant_type or variant_type,
        )
    )
    trace("selector_done")
    selected_courses = [
        item for item in selected_courses
        if item.get("course_id") is None or int(item.get("course_id")) not in excluded_course_ids
    ]
    selected_courses = _unique_items_by_title(selected_courses)
    selected_courses = _remap_equivalent_prerequisites(selected_courses, db)
    domain_repair_candidates = [dict(item) for item in selected_courses]
    selected_real_ids = {
        int(item["course_id"]) for item in selected_courses if item.get("course_id") is not None
    }
    # GOSO outcomes are covered by the regulatory block merged immediately
    # after selection.  Requiring ordinary EPVO electives to cover them before
    # that merge made every KZ plan look incomplete and forced synthetic
    # integration bridges into otherwise valid standard programmes.
    professional_los = [
        lo for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    ]
    real_lo_coverage = {lo.id: 0.0 for lo in professional_los}
    if selected_real_ids and real_lo_coverage:
        for match in db.query(MatchScore).filter(
            MatchScore.project_version_id == project_version_id,
            MatchScore.course_id.in_(selected_real_ids),
        ).all():
            expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
            if match.lo_id in real_lo_coverage:
                real_lo_coverage[match.lo_id] = max(
                    real_lo_coverage.get(match.lo_id, 0.0), float(match.score or 0.0), expert
                )
    selector_has_complete_real_lo = bool(real_lo_coverage) and all(
        score >= 0.5 for score in real_lo_coverage.values()
    )
    selector_has_bridges = any(item.get("bridge_module_id") is not None for item in selected_courses)
    if not selector_has_complete_real_lo or selector_has_bridges:
        selected_courses = _normalize_selected_courses_for_quality(
            selected_courses, project_version, db, variant_type
        )
    selected_courses = merge_goso_items(selected_courses, project_version, db)
    # The selector already runs a fractional two-domain quota repair for an
    # interdisciplinary programme.  The historical one-domain exact fitter
    # below is valuable for ordinary KZ plans, but it rebuilds the remainder
    # after ГОСО with a single domain label and can discard those reservations.
    # Keep the quota-aware selection intact; later validation still rejects a
    # real deficit rather than masking it with bridges.
    if str(constraints.get("program_type") or "standard").lower() not in {
        "interdisciplinary", "joint"
    }:
        selected_courses = _fit_real_professional_block_after_goso(
            selected_courses, project_version, db, variant_type
        )
    if not selector_has_complete_real_lo:
        selected_courses = _ensure_foundation_capacity(
            selected_courses, project_version, db
        )
    # Foundation-capacity repair can rebuild the candidate subset. Run the
    # competency pass after it so a required ICT block (notably information
    # security) cannot be discarded by the later fallback.
    selected_courses = _repair_missing_ict_competencies(
        selected_courses, project_version, db, variant_type
    )
    trace("course_repairs_done")
    confirmed_bridge_ids = {
        int(bridge_id)
        for bridge_id in (constraints.get("confirmed_bridge_replacements") or {})
        if str(bridge_id).isdigit()
    }
    build_program_type = str(constraints.get("program_type") or "standard").lower()
    build_is_interdisciplinary = (
        build_program_type in {"interdisciplinary", "joint"}
        and bool(str(project_version.project.domain2 or "").strip())
    )
    meaningful_bridges: List[BridgeModule | None] = []
    if constraints.get("allow_new_courses", True) and build_is_interdisciplinary:
        bridge_ids = {
            int(item["bridge_module_id"])
            for item in selected_courses
            if item.get("bridge_module_id") is not None
        }
        bridge_codes = {
            module.id: str(module.course_id or "")
            for module in db.query(BridgeModule).filter(
                BridgeModule.id.in_(bridge_ids or {-1})
            ).all()
        }
        selected_courses = [
            item for item in selected_courses
            if not str(bridge_codes.get(item.get("bridge_module_id"), "")).startswith(
                ("AUTO_BRIDGE_", "AUTO_LOAD_SHIFT_", "AUTO_BALANCE_", "QUALITY_BRIDGE_")
            )
        ]
        # The integration module is structural evidence that the two selected
        # fields are taught together. It is required even when separate real
        # courses already cover every LO; generic credit-gap bridges are not.
        meaningful_bridges = [
            ensure_core_interdisciplinary_bridge(project_version, db),
            *sorted(
                ensure_secondary_domain_bridge_modules(project_version, db),
                key=lambda bridge: 0 if str(bridge.course_id or "").startswith("SECONDARY_INTEGRATION_") else 1,
            ),
        ]
        target = int(constraints.get("total_credits", 240))
        for index, bridge in enumerate(meaningful_bridges):
            if bridge is None or bridge.id in confirmed_bridge_ids:
                continue
            # Keep the secondary-domain bridge even when the real-course
            # shortlist already reaches the target.  In an interdisciplinary
            # plan this bridge is evidence for the second domain and may be
            # inserted by replacing a non-regulatory course; skipping it made
            # variants A/B fail the 40% domain quota while C happened to pass.
            selected_courses = _force_bridge_item(
                selected_courses,
                bridge,
                variant_type,
                target,
            )
        integration = next(
            (bridge for bridge in meaningful_bridges
             if bridge is not None and str(bridge.course_id or "").startswith("SECONDARY_INTEGRATION_")),
            None,
        )
        if integration is not None and not any(
            int(item.get("bridge_module_id") or 0) == integration.id
            for item in selected_courses
        ):
            # A confirmed generic gap bridge can consume the hard bridge
            # budget before the structural integration module is admitted.
            # Release that slot explicitly; the integration module is the
            # auditable evidence for the second-domain quota.
            generic_index = next(
                (index for index, item in enumerate(selected_courses)
                 if str(bridge_codes.get(item.get("bridge_module_id"), "")).startswith(
                     ("LO_GAP_BRIDGE_", "AUTO_BRIDGE_", "QUALITY_BRIDGE_", "AUTO_BALANCE_", "AUTO_LOAD_SHIFT_"))),
                None,
            )
            if generic_index is not None:
                selected_courses.pop(generic_index)
            selected_courses = _force_bridge_item(
                selected_courses, integration, variant_type, target
            )
        selected_courses = _cap_bridge_items_to_budget(
            selected_courses, project_version, confirmed_bridge_ids
        )
    selected_courses = _unique_items_by_title(selected_courses)
    selected_courses = _remap_equivalent_prerequisites(selected_courses, db)
    num_semesters = int(constraints.get("total_semesters", 8))
    nominal_load = int(constraints.get("max_credits_per_semester", 30))
    target_credits = int(constraints.get("total_credits", 240))
    maximum_credits = target_credits + max(0, int(constraints.get("credit_tolerance", TOTAL_CREDIT_TOLERANCE)))
    selected_courses = _trim_to_target_credits(selected_courses, target_credits, db)
    project_domains = _project_domain_terms(project_version, db)
    declared_secondary_domain = str(project_version.project.domain2 or "").casefold().strip()
    interdisciplinary_professional = str(constraints.get("program_type") or "standard").lower() in {"interdisciplinary", "joint"}
    cyber_forensics_program = (
        any("it" in d or "информ" in d or "computer" in d or "кибер" in d for d in project_domains)
        and any("forensic" in d or "криминал" in d or "расслед" in d for d in project_domains)
    )
    match_max_by_course = {
        int(row.course_id): float(row.max_score or 0.0)
        for row in db.query(MatchScore.course_id, func.max(MatchScore.score).label("max_score"))
        .filter(MatchScore.project_version_id == project_version_id)
        .group_by(MatchScore.course_id)
        .all()
    }

    # Keep admission policy as an explicit dependency instead of a nested
    # closure.  This makes the scheduler orchestration easier to inspect and
    # lets unit tests exercise the exact same admission contract directly.
    is_project_domain = partial(
        _is_course_in_project_domain,
        excluded_course_ids=excluded_course_ids,
        education_level=constraints.get("education_level"),
        project_domains=project_domains,
        declared_secondary_domain=declared_secondary_domain,
        interdisciplinary_professional=interdisciplinary_professional,
        cyber_forensics_program=cyber_forensics_program,
        match_max_by_course=match_max_by_course,
        education_level_check=_education_level_course_allowed,
        domain_match=_course_domain_matches,
        domain_label_match=domain_label_matches,
        title_relevant=_is_interdisciplinary_title_relevant,
        curriculum_role=_course_curriculum_role,
    )
    sanitize_selected_courses = partial(
        sanitize_admitted_course_items,
        project_version_id=project_version_id,
        professional_los=professional_los,
        project_domains=project_domains,
        constraints=constraints,
        is_project_domain=is_project_domain,
        curriculum_role=_course_curriculum_role,
        match_max_by_course=match_max_by_course,
        db=db,
    )

    selected_courses = sanitize_selected_courses(selected_courses)
    # Late domain/credit repairs can remove the only real source for an LO.
    # Restore an evidence-backed original candidate before scheduling, using
    # a same-credit bridge or weak real item as the exchange slot. This keeps
    # the verifier strict while preventing B/C diversification from silently
    # losing professional outcomes.
    covered_lo_codes = {
        code for item in selected_courses for code in (item.get("admission_los") or [])
    }
    required_lo_codes = {
        str(lo.lo_code or "") for lo in professional_los if str(lo.lo_code or "")
    }
    missing_lo_codes = required_lo_codes - covered_lo_codes
    if missing_lo_codes:
        selected_ids = {
            int(item["course_id"]) for item in selected_courses
            if item.get("course_id") is not None
        }
        for candidate in domain_repair_candidates:
            candidate_los = set(candidate.get("admission_los") or [])
            course_id = candidate.get("course_id")
            if not candidate_los.intersection(missing_lo_codes) or course_id in selected_ids:
                continue
            replacement_index = next(
                (
                    index for index, item in enumerate(selected_courses)
                    if item.get("bridge_module_id") is not None
                    and int(item.get("credits") or 0) == int(candidate.get("credits") or 0)
                ),
                None,
            )
            if replacement_index is None:
                continue
            selected_courses[replacement_index] = dict(candidate)
            selected_ids.add(int(course_id))
            covered_lo_codes.update(candidate_los)
            missing_lo_codes -= candidate_los
            if not missing_lo_codes:
                break
    selected_courses = _trim_to_target_credits(selected_courses, target_credits, db)
    # Final candidate repairs can reintroduce a second generic foundation
    # after the earlier normalization pass.  Deduplicate once immediately
    # before scheduling so a late duplicate cannot create a false semester
    # violation or consume professional-course capacity.
    selected_courses = _unique_items_by_title(selected_courses)
    selected_courses = _apply_scoped_epvo_semesters(selected_courses, project_version, db)

    previous_offending: frozenset[int] | None = None
    for _ in range(12):
        # Prerequisite repair may append replacement courses after the initial
        # EPVO-semester pass. Re-attach the selected direction/group evidence
        # before every scheduling attempt so replacements follow the same
        # education-level and semester rules.
        selected_courses = _apply_scoped_epvo_semesters(selected_courses, project_version, db)
        # This is the last candidate boundary before scheduling. Reassert the
        # ICT competency contract here because any preceding normalization or
        # credit repair may have replaced the marked security course.
        selected_courses = _repair_missing_ict_competencies(
            selected_courses, project_version, db, variant_type
        )
        if interdisciplinary_professional:
            integration = next(
                (bridge for bridge in ensure_secondary_domain_bridge_modules(project_version, db)
                 if str(bridge.course_id or "").startswith("SECONDARY_INTEGRATION_")),
                None,
            )
            if integration is not None and not any(
                int(item.get("bridge_module_id") or 0) == integration.id
                for item in selected_courses
            ):
                selected_courses = [
                    item for item in selected_courses
                    if not str(item.get("title") or "").startswith("Модуль закрытия пробелов")
                ]
                selected_courses = _force_bridge_item(
                    selected_courses, integration, variant_type, target_credits
                )
        # Do not replace the fitted post-GOSO timetable with the raw selector
        # pool when an LO is missing. That pool can contain an entire 180-credit
        # professional block, while the mandatory block has already consumed
        # most of the degree budget. The independent final verifier must expose
        # an unresolved LO rather than silently turning a 180-credit plan into
        # an over-credit one. Evidence-backed repairs below can still close it.
        schedule = schedule_courses(selected_courses, num_semesters, nominal_load, db)
        schedule = _relocate_bounded_bridges(schedule, num_semesters, nominal_load, db)
        verification = verify_curriculum_plan(schedule, project_version, db)
        offending = {item["course_id"] for item in verification["prerequisite_violations"] if item.get("course_id") is not None}
        if not offending: break
        # A repair that produces the same offending set cannot make progress:
        # repeating normalization and verification only burns minutes and
        # leaves the user with a generic timeout. Let the final verifier report
        # the stable violation instead of looping over an unchanged state.
        current_offending = frozenset(int(course_id) for course_id in offending)
        if current_offending == previous_offending:
            break
        previous_offending = current_offending
        selected_courses = [item for item in selected_courses if item.get("course_id") not in offending]
        selected_ids = {item.get("course_id") for item in selected_courses if item.get("course_id") is not None}
        total = sum(item.get("credits") or 0 for item in selected_courses)
        replacements = [
            course for course in db.query(Course).options(selectinload(Course.prerequisites)).filter(
                Course.id.in_(list(match_max_by_course) or [-1])
            ).all()
            if course.id not in selected_ids and not course.prerequisites and is_project_domain(course)
        ]
        replacements.sort(key=lambda course: (0 if (course.domain or "").lower() in {(project_version.project.domain1 or "").lower(), (project_version.project.domain2 or "").lower()} else 1, course.credits or 5, course.id))
        for course in replacements:
            credits = course.credits or 5
            if total + credits > maximum_credits: continue
            selected_courses.append({"course_id": course.id, "title": course.title, "domain": course.domain, "credits": credits, "recommended_semester": course.recommended_semester, "prerequisites": [], "type": course.cycle_component or "mandatory"})
            total += credits
            if total >= target_credits: break
        if total < target_credits and constraints.get("allow_new_courses", True):
            existing_bridge_count = sum(1 for item in selected_courses if item.get("bridge_module_id"))
            slots = max(0, int(constraints.get("max_new_courses", 5)) - existing_bridge_count)
            for bm in ensure_credit_bridge_modules(project_version, db, target_credits - total, slots):
                credits = bm.credits or 5
                if total + credits > maximum_credits:
                    continue
                selected_courses.append({
                    "bridge_module_id": bm.id,
                    "title": bm.title,
                    "domain": "interdisciplinary",
                    "credits": credits,
                    "recommended_semester": bm.recommended_semester,
                    "prerequisites": bm.prerequisites or [],
                    "type": "bridge",
                })
                total += credits
                if total >= target_credits:
                    break
        selected_courses = _normalize_selected_courses_for_quality(selected_courses, project_version, db, variant_type)
        selected_courses = merge_goso_items(selected_courses, project_version, db)
        selected_courses = _unique_items_by_title(selected_courses)
        selected_courses = _remap_equivalent_prerequisites(selected_courses, db)
        selected_courses = sanitize_selected_courses(selected_courses)
        selected_courses = _trim_to_target_credits(selected_courses, target_credits, db)

    # The prerequisite loop may rebuild the exact candidate subset and discard
    # a competency repair marker. Re-run this quality-critical pass at the
    # final selection boundary so required ICT blocks survive every repair.
    selected_courses = _repair_missing_ict_competencies(
        selected_courses, project_version, db, variant_type
    )

    # Fill an ordinary credit gap with several distinct, auditable modules.
    # Previously the final repair could turn one subject into a 60-credit
    # pseudo-course after duplicate catalogue rows were removed.
    selected_courses = sanitize_selected_courses(selected_courses)
    selected_courses = merge_goso_items(selected_courses, project_version, db)
    # Selection can inherit several low-evidence bridge rows from the
    # candidate/repair stages. Enforce the same budget before structural
    # interdisciplinary bridges are added; otherwise later credit repair can
    # produce a plan that is technically complete but pedagogically unusable.
    selected_courses = _cap_bridge_items_to_budget(
        selected_courses, project_version, confirmed_bridge_ids
    )
    if interdisciplinary_professional:
        integration = next(
            (bridge for bridge in ensure_secondary_domain_bridge_modules(project_version, db)
             if str(bridge.course_id or "").startswith("SECONDARY_INTEGRATION_")),
            None,
        )
        if integration is not None and not any(
            int(item.get("bridge_module_id") or 0) == integration.id for item in selected_courses
        ):
            selected_courses = [
                item for item in selected_courses
                if not str(item.get("title") or "").startswith("Модуль закрытия пробелов")
            ]
            selected_courses = _force_bridge_item(
                selected_courses, integration, variant_type, target_credits
            )
        selected_ids = {
            int(item["course_id"]) for item in selected_courses
            if item.get("course_id") is not None
        }
        selected_titles = {_title_key(item.get("title")) for item in selected_courses}
        credible_secondary_ids = set(
            _credible_professional_lo_by_course(
                project_version,
                set(match_max_by_course),
                db,
            )
        )
        # ``match_max_by_course`` is the authoritative candidate frontier for
        # this build.  Scanning the complete catalogue here once per variant
        # made the planner spend minutes in an O(|catalogue|) pass despite
        # discarding every unscored row below.
        secondary_courses = [
            course for course in db.query(Course).options(selectinload(Course.prerequisites)).filter(
                Course.id.in_(match_max_by_course.keys() or {-1})
            ).all()
            if course.id not in selected_ids
            and _title_key(course.title) not in selected_titles
            and 3 <= int(course.credits or 0) <= 7
            and domain_label_matches(course.domain, [project_version.project.domain2])
            and not course.prerequisites
            and course.id in match_max_by_course
            and match_max_by_course.get(course.id, 0.0) >= 0.4
            and course.id in credible_secondary_ids
        ]
        if secondary_courses:
            replacement = next(
                (item for item in selected_courses
                 if item.get("course_id") is not None
                 and not item.get("regulatory_required")
                 and not item.get("competency_required")
                 and 3 <= int(item.get("credits") or 0) <= 7
                 and not item.get("prerequisites")),
                None,
            )
            if replacement is not None:
                course = next(
                    (candidate for candidate in secondary_courses
                     if int(candidate.credits or 0) == int(replacement.get("credits") or 0)),
                    secondary_courses[0],
                )
                if int(course.credits or 0) != int(replacement.get("credits") or 0):
                    course = None
                if course is not None:
                    replacement.update({
                    "course_id": course.id,
                    "title": course.title,
                    "domain": course.domain,
                    "credits": int(course.credits or 0),
                    "recommended_semester": course.recommended_semester,
                    "prerequisites": [],
                    "admission_los": [
                        lo.lo_code for lo in db.query(LearningOutcome).filter(
                            LearningOutcome.id.in_([row.lo_id for row in db.query(MatchScore).filter(
                            MatchScore.project_version_id == project_version.id,
                            MatchScore.course_id == course.id,
                            ).order_by(MatchScore.score.desc()).limit(3).all()])
                        ).all()
                    ],
                    })
    total_before_gap_fill = sum(int(item.get("credits") or 0) for item in selected_courses)
    if total_before_gap_fill < target_credits and constraints.get("allow_new_courses", True):
        existing_bridge_ids = {
            item.get("bridge_module_id")
            for item in selected_courses
            if item.get("bridge_module_id") is not None
        }
        maximum_bridge_slots = bridge_module_limit(project_version)
        available_slots = max(0, maximum_bridge_slots - len(existing_bridge_ids))
        for module in ensure_credit_bridge_modules(
            project_version,
            db,
            min(maximum_credits - total_before_gap_fill, target_credits - total_before_gap_fill),
            available_slots,
            desired_count=available_slots,
        ):
            if module.id in existing_bridge_ids:
                continue
            credits = int(module.credits or 5)
            if total_before_gap_fill + credits > maximum_credits:
                continue
            selected_courses.append({
                "bridge_module_id": module.id, "title": module.title,
                "domain": "interdisciplinary", "credits": credits,
                "recommended_semester": module.recommended_semester,
                "prerequisites": module.prerequisites or [], "type": "bridge",
            })
            existing_bridge_ids.add(module.id)
            total_before_gap_fill += credits
            if total_before_gap_fill >= target_credits:
                break

        # Use the permitted 3–7 credit range before inventing another module.
        remaining_gap = max(0, target_credits - total_before_gap_fill)
        for item in reversed(selected_courses):
            if remaining_gap <= 0:
                break
            if item.get("bridge_module_id") is None:
                continue
            room = max(0, 7 - int(item.get("credits") or 0))
            increase = min(room, remaining_gap)
            if increase <= 0:
                continue
            item["credits"] = int(item.get("credits") or 0) + increase
            module = db.query(BridgeModule).filter(BridgeModule.id == item["bridge_module_id"]).first()
            if module:
                module.credits = item["credits"]
            total_before_gap_fill += increase
            remaining_gap -= increase
        selected_courses = _trim_to_target_credits(selected_courses, target_credits, db)

    if meaningful_bridges:
        late_bridge_ids = {
            int(item["bridge_module_id"])
            for item in selected_courses
            if item.get("bridge_module_id") is not None
        }
        late_bridge_codes = {
            module.id: str(module.course_id or "")
            for module in db.query(BridgeModule).filter(
                BridgeModule.id.in_(late_bridge_ids or {-1})
            ).all()
        }
        selected_courses = [
            item for item in selected_courses
            if not str(late_bridge_codes.get(item.get("bridge_module_id"), "")).startswith(
                ("AUTO_BRIDGE_", "AUTO_LOAD_SHIFT_", "AUTO_BALANCE_", "QUALITY_BRIDGE_")
            )
        ]
        for bridge in meaningful_bridges:
            if bridge is None or bridge.id in confirmed_bridge_ids:
                continue
            if (
                bridge is not meaningful_bridges[0]
                and sum(int(item.get("credits") or 0) for item in selected_courses)
                >= target_credits
                and not str(bridge.course_id or "").startswith("SECONDARY_")
            ):
                break
            selected_courses = _force_bridge_item(
                selected_courses, bridge, variant_type, target_credits
            )
        selected_courses = _trim_to_target_credits(
            selected_courses, target_credits, db
        )

    if (
        variant_type == "C"
        and str(constraints.get("education_level") or "").lower()
        in {"doctorate", "doctoral", "phd"}
    ):
        preferred_semester = max(1, num_semesters - 1)
        trajectory_candidates = [
            item for item in selected_courses
            if item.get("course_id") is not None
            and not item.get("regulatory_required")
            and not item.get("competency_required")
            # Doctoral professional blocks commonly use 3–4 credit courses;
            # requiring exactly five here made the C trajectory nudge a no-op.
            and int(item.get("credits") or 0) > 0
            and _foundation_max_semester(item.get("title"), num_semesters)
            >= preferred_semester
        ]
        if trajectory_candidates:
            trajectory_item = max(
                trajectory_candidates,
                key=lambda item: int(item.get("course_id") or 0),
            )
            trajectory_item["variant_preferred_semester"] = preferred_semester
            trajectory_item["latest_semester"] = max(
                preferred_semester,
                int(trajectory_item.get("latest_semester") or 1),
            )
    elif (
        variant_type == "B"
        and str(constraints.get("education_level") or "").lower()
        in {"doctorate", "doctoral", "phd"}
    ):
        # When the doctoral catalogue has only one credit-balanced competency
        # exchange, B and A can still converge on the same course set.  Give B
        # a real trajectory alternative by moving one unprotected professional
        # unit to semester 2; this changes sequencing only and leaves credits,
        # prerequisites, level and competency evidence untouched.
        trajectory_candidates = [
            item for item in selected_courses
            if item.get("course_id") is not None
            and not item.get("regulatory_required")
            and not item.get("competency_required")
            and not item.get("prerequisites")
            and int(item.get("credits") or 0) > 0
            and int(item.get("recommended_semester") or 1) <= 1
        ]
        if trajectory_candidates:
            trajectory_item = max(
                trajectory_candidates,
                key=lambda item: int(item.get("course_id") or 0),
            )
            trajectory_item["variant_preferred_semester"] = 3
            trajectory_item["latest_semester"] = max(
                3, int(trajectory_item.get("latest_semester") or 1)
            )

    # Close residual credit/load gaps even when prerequisite verification was
    # already clean. This fixes plans such as 238/240 with a 24-credit semester.
    residual_gap = target_credits - sum(
        int(item.get("credits") or 0) for item in selected_courses
    )
    if 3 <= residual_gap <= 7:
        selected_ids = {
            int(item["course_id"])
            for item in selected_courses
            if item.get("course_id") is not None
        }
        selected_titles = {
            _title_key(item.get("title"))
            for item in selected_courses
            if item.get("title")
        }
        residual_ids = {
            int(item["course_id"])
            for item in domain_repair_candidates
            if item.get("course_id") is not None
            and int(item.get("credits") or 0) == residual_gap
            and int(item["course_id"]) not in selected_ids
            and _title_key(item.get("title")) not in selected_titles
        }
        if residual_gap <= 7:
            # Include scored repository candidates that were not in the
            # selector's already-normalized subset; they are needed when a
            # late variant-specific repair removed the only exact-gap item.
            residual_ids.update(
                int(course_id)
                for (course_id,) in db.query(Course.id).filter(
                    Course.id.in_(list(match_max_by_course) or [-1]),
                    Course.credits == residual_gap,
                ).all()
            )
        residual_courses = {
            course.id: course
            for course in db.query(Course).options(selectinload(Course.prerequisites)).filter(
                Course.id.in_(residual_ids or {-1})
            ).all()
        }
        residual_evidence = _credible_professional_lo_by_course(
            project_version, residual_ids, db
        )
        residual_candidates = []
        for candidate in domain_repair_candidates:
            course_id = candidate.get("course_id")
            if course_id is None or int(course_id) not in residual_ids:
                continue
            course = residual_courses.get(int(course_id))
            prerequisites = {
                int(value) for value in (candidate.get("prerequisites") or [])
            }
            if (
                course is None
                or int(course_id) not in residual_evidence
                or not prerequisites.issubset(selected_ids)
                or not _education_level_course_allowed(
                    course, constraints.get("education_level")
                )
                or _has_foreign_professional_title(course, project_domains)
                or (
                    build_is_interdisciplinary
                    and not _is_it_medicine_support_course(
                        course, project_domains
                    )
                )
            ):
                continue
            residual_candidates.append(candidate)
        residual_candidates.sort(key=lambda item: (
            -float(item.get("admission_score") or item.get("score") or 0.0),
            int(item.get("recommended_semester") or 99),
            int(item.get("course_id") or 0),
        ))
        # A variant can lose a real course during late competency/domain
        # normalization even when the original selected subset had no exact
        # residual candidate.  Do not silently leave (for example) 236/240
        # credits just because the bridge budget is already full: use a scored,
        # unused repository course with the exact gap and the same admission
        # gates.  This keeps credit repair semantic and auditable.
        if not residual_candidates and residual_gap <= 7:
            selected_titles = {
                _title_key(item.get("title"))
                for item in selected_courses
                if item.get("title")
            }
            fallback_courses = db.query(Course).options(selectinload(Course.prerequisites)).filter(
                Course.id.in_(list(match_max_by_course) or [-1]),
                Course.credits == residual_gap,
            ).all()
            for course in fallback_courses:
                if (
                    course.id in selected_ids
                    or _title_key(course.title) in selected_titles
                    or not is_project_domain(course)
                    or course.prerequisites
                    or _has_foreign_professional_title(course, project_domains)
                    or (
                        build_is_interdisciplinary
                        and not _is_it_medicine_support_course(course, project_domains)
                    )
                    or course.id not in residual_evidence
                ):
                    continue
                residual_candidates.append({
                    "course_id": course.id,
                    "title": course.title,
                    "domain": course.domain,
                    "credits": int(course.credits or 0),
                    "recommended_semester": course.recommended_semester,
                    "prerequisites": [],
                    # Keep the same admission contract as candidates coming
                    # from retrieval.  Without this field the later
                    # sanitize_selected_courses gate correctly (but
                    # incorrectly for this already-evidenced fallback)
                    # discarded the real credit-fill course.
                    "admission_los": sorted(residual_evidence.get(course.id, set())),
                    "type": course.cycle_component or "mandatory",
                    "score": match_max_by_course.get(course.id, 0.0),
                })
                break
        if residual_candidates:
            real_fill = dict(residual_candidates[0])
            real_fill["selection_method"] = "final_real_credit_fill"
            selected_courses.append(real_fill)

    selected_courses = _apply_scoped_epvo_semesters(selected_courses, project_version, db)
    # An explicitly introductory course with an early source semester is not
    # a generic load shuttle.  Interdisciplinary balancing used to move such a
    # foundation to the final semester when bridge modules filled the early
    # terms, producing a real semantic violation (for example "Введение в
    # биологию" in semester 8).  Mark the source placement as required so the
    # scheduler and subsequent load repairs preserve its admissible window.
    for item in selected_courses:
        title = str(item.get("title") or "").casefold().strip()
        recommended = int(item.get("recommended_semester") or 0)
        if (
            recommended == 1
            and title.startswith(("введение ", "основы ", "introduction ", "fundamentals "))
            and item.get("course_id") is not None
        ):
            item["_scoped_epvo_semester"] = True
            item["source_semester_required"] = True
    schedule = schedule_courses(selected_courses, num_semesters, nominal_load, db)
    trace("schedule_courses_done")
    schedule = _relocate_bounded_bridges(schedule, num_semesters, nominal_load, db)
    invariant_ledger = InvariantLedger(num_semesters)
    invariant_ledger.record("scheduled", schedule)
    provisional = verify_curriculum_plan(schedule, project_version, db)
    total_now = sum(int(item.get("credits") or 0) for item in selected_courses)
    load_gaps = [
        (int(item["semester"]), max(0, math.ceil(item["allowed_min"] - item["credits"])))
        for item in provisional["semester_load_violations"]
        if item.get("credits", 0) < item.get("allowed_min", 0)
    ]
    credit_gap = max(0, target_credits - total_now)
    target_semester, load_gap = max(load_gaps, key=lambda item: item[1], default=(1, 0))
    repair_credits = max(credit_gap, load_gap)
    repair_credits = min(7, repair_credits)
    if 0 < repair_credits < 3:
        repair_credits = 0
    bridge_count = sum(
        1 for items in schedule.values() for item in items
        if item.get("bridge_module_id") is not None
    )
    if (repair_credits > 0 and total_now + repair_credits <= maximum_credits
            and bridge_count < bridge_module_limit(project_version)):
        code = f"AUTO_BALANCE_{project_version.id}_{target_semester}"
        balance = db.query(BridgeModule).filter(
            BridgeModule.project_version_id == project_version.id,
            BridgeModule.course_id == code,
        ).first()
        if balance is None:
            balance = BridgeModule(
                project_version_id=project_version.id, course_id=code,
                title=f"Интегрированный практический модуль семестра {target_semester}",
                goal="Сбалансировать нагрузку семестра и подготовить подтверждения достижения результатов обучения.",
                description="Руководимая междисциплинарная практика, портфолио подтверждений и рефлексивная защита.",
                credits=repair_credits, recommended_semester=target_semester,
                learning_outcomes=["Интегрировать знания семестра в прикладной профессиональной задаче."],
                topics=["Интегрированный кейс", "Прикладная практика", "Портфолио подтверждений", "Рефлексия и защита"],
                prerequisites=[], assessment_methods=["портфолио", "проектный кейс", "защита"],
                source_chunks_json=[], generation_params_json={"mode": "final_credit_and_load_repair"},
                # Credit/load repair has no independent programme-LO evidence.
                # Do not claim all programme outcomes merely because the
                # module was inserted into a semester.
                target_los=[],
            )
            db.add(balance); db.flush()
        else:
            balance.credits = repair_credits; balance.recommended_semester = target_semester
        selected_courses.append({
            "bridge_module_id": balance.id, "title": balance.title,
            "domain": "interdisciplinary", "credits": repair_credits,
            "recommended_semester": target_semester, "latest_semester": target_semester,
            "prerequisites": [], "type": "bridge",
        })
        # Direct placement is intentional: running the global scheduler again
        # can move unrelated prerequisite chains and recreate the imbalance.
        schedule[target_semester].append(selected_courses[-1])
        overshoot = total_now + repair_credits - target_credits
        if overshoot > 0:
            loads_after = {
                semester: sum(int(item.get("credits") or 0) for item in items)
                for semester, items in schedule.items()
            }
            donors = sorted(schedule, key=lambda semester: loads_after[semester], reverse=True)
            for donor_semester in donors:
                if loads_after[donor_semester] - overshoot < provisional["allowed_semester_load"]["min"]:
                    continue
                donor = next((item for item in schedule[donor_semester]
                              if item.get("bridge_module_id") not in (None, balance.id)
                              and int(item.get("credits") or 0) > overshoot
                              and int(item.get("credits") or 0) - overshoot >= 3), None)
                if donor is None:
                    continue
                donor["credits"] = int(donor["credits"]) - overshoot
                donor_module = db.query(BridgeModule).filter(BridgeModule.id == donor["bridge_module_id"]).first()
                if donor_module:
                    donor_module.credits = donor["credits"]
                break
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    schedule = _strict_rebalance_max_load(schedule, num_semesters, nominal_load + 3)
    schedule = _trim_schedule_to_target_credits(schedule, target_credits, db)
    schedule = _strict_rebalance_max_load(schedule, num_semesters, nominal_load + 3)
    schedule = _shift_excess_load_to_balance_modules(schedule, project_version, nominal_load, db)
    schedule = _trim_schedule_to_target_credits(schedule, target_credits, db)
    schedule = _repair_semester_appropriateness(
        schedule, num_semesters, nominal_load, db
    )
    trace("semester_repair_1_done")
    schedule = _repair_underloaded_semesters_with_bridges(
        schedule, project_version, nominal_load, target_credits, maximum_credits, db
    )
    trace("underloaded_bridge_repair_done")
    # Flexible bridge credits can change by one during residual repair. Run
    # the bounded whole-course/swap balancer once more so a valid 3↔4 credit
    # exchange is not left as a 26-credit semester.
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    trace("rebalance_1_done")
    # The residual-load repair is intentionally the last credit operation, but
    # it can change which semester has room for a foundation course.  Re-run
    # the semantic repair so the persisted plan, not only the provisional
    # schedule, satisfies the same semester bounds as the verifier.
    schedule = _repair_semester_appropriateness(
        schedule, num_semesters, nominal_load, db
    )
    trace("semester_repair_2_done")
    # Domain quota repair is intentionally deferred until the final mutation
    # boundary below. Running it here and then mutating the schedule again
    # caused the same expensive search to execute repeatedly per variant.
    trace("domain_repair_deferred_1")
    invariant_ledger.record("final_repair_boundary", schedule)
    # Equal-credit quota swaps preserve load, but a replacement can have a
    # different semantic study window. Keep the persisted semester ordering
    # subject to the same final appropriateness rule.
    schedule = _repair_semester_appropriateness(
        schedule, num_semesters, nominal_load, db
    )
    # The inferred graph can make a late source recommendation authoritative
    # and therefore change the admissible semester window. Build it before
    # the final admission repair, then rebuild after any bounded swap.
    prerequisite_graph = _infer_schedule_prerequisites(schedule)
    schedule = _repair_final_admission_misplacements(
        schedule, domain_repair_candidates, project_version, db
    )
    schedule = _fill_schedule_credit_gap(
        schedule, project_version, target_credits, maximum_credits, db,
        # Late quota/quality repairs may remove a real course from the active
        # list while retaining it in the pre-repair domain candidate pool.
        # Offer both pools at the final boundary; the gap helper deduplicates
        # by course_id and admits only courses not already scheduled.
        real_candidates=[*selected_courses, *domain_repair_candidates],
    )
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    schedule = _strict_rebalance_max_load(schedule, num_semesters, nominal_load + 3)
    # Rebalancing can expose a residual gap after the first bridge repair.
    # Run the bounded repair once more at the final envelope; no later step
    # removes these explicit bridge credits.
    schedule = _fill_schedule_credit_gap(
        schedule, project_version, target_credits, maximum_credits, db,
        real_candidates=selected_courses,
    )
    prerequisite_graph = _infer_schedule_prerequisites(schedule)
    # The final credit-gap repair may move flexible courses after the normal
    # semantic pass. Re-apply the bounded semester-improvement pass last so
    # EPVO-recommended semesters are respected in the persisted schedule too.
    schedule = _repair_semester_appropriateness(
        schedule, num_semesters, nominal_load, db
    )
    # Credit balancing and final bridge-gap repair can still move a real
    # course after the earlier admission pass. Apply the independent gate at
    # the true end of the pipeline, then restore semantic placement once; no
    # later operation is allowed to undo this ordering.
    schedule = _repair_final_admission_misplacements(
        schedule, domain_repair_candidates, project_version, db
    )
    schedule = _repair_semester_appropriateness(
        schedule, num_semesters, nominal_load, db
    )
    # Admission/semantic repairs can leave a late semester underloaded after
    # a domain swap. Stabilize the load envelope at the final boundary before
    # competency and domain assertions; this pass only moves admissible items
    # and cannot change credits or domain quotas.
    schedule = _repair_underloaded_semesters_with_bridges(
        schedule, project_version, nominal_load, target_credits, maximum_credits, db
    )
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    # The residual bridge pass may add credits after the ordinary balancer.
    # Close the pipeline with the strict envelope as well; otherwise a valid
    # 33-credit semester can become 34 and reach the verifier unchanged.
    schedule = _strict_rebalance_max_load(schedule, num_semesters, nominal_load + 3)

    # Final schedule guard: load/quota repairs operate on a flat schedule and
    # can otherwise replace the only course carrying an ICT competency block.
    # Restore a same-credit, scoped EPVO competency candidate in-place before
    # the independent verifier runs; no synthetic bridge is accepted here.
    competency_requirements = _ict_competency_requirements(constraints)
    if competency_requirements:
        final_course_ids = {
            int(item["course_id"])
            for rows in schedule.values()
            for item in rows
            if item.get("course_id") is not None
        }
        final_courses = {
            course.id: course
            for course in db.query(Course).options(selectinload(Course.prerequisites)).filter(
                Course.id.in_(final_course_ids or {-1})
            ).all()
        }
        final_audit = _ict_competency_audit(list(final_courses.values()), constraints)
        if final_audit.get("missing"):
            flat_items = [dict(item) for rows in schedule.values() for item in rows]
            repaired_items = _repair_missing_ict_competencies(
                flat_items, project_version, db, variant_type
            )
            repaired_by_id = {
                int(item["course_id"]): item
                for item in repaired_items
                if item.get("course_id") is not None
                and int(item["course_id"]) not in final_course_ids
                and item.get("competency_required")
            }
            selected_prerequisites = {
                int(prerequisite_id)
                for rows in schedule.values()
                for item in rows
                for prerequisite_id in (item.get("prerequisites") or [])
                if prerequisite_id in final_course_ids
            }
            for candidate in repaired_by_id.values():
                candidate_credits = int(candidate.get("credits") or 0)
                replaceable = [
                    (semester, index, item)
                    for semester, rows in schedule.items()
                    for index, item in enumerate(rows)
                    if item.get("course_id") is not None
                    and not item.get("regulatory_required")
                    and not item.get("competency_required")
                    and int(item.get("course_id")) not in selected_prerequisites
                    and int(item.get("credits") or 0) == candidate_credits
                ]
                if not replaceable:
                    continue
                semester, index, old_item = min(
                    replaceable,
                    key=lambda row: (
                        float(row[2].get("admission_score") or 0.0),
                        -int(row[2].get("credits") or 0),
                    ),
                )
                replacement = dict(candidate)
                replacement["recommended_semester"] = semester
                replacement["selection_method"] = "ict_competency_final_guard"
                schedule[semester][index] = replacement
                final_course_ids.discard(int(old_item["course_id"]))
                final_course_ids.add(int(candidate["course_id"]))
                final_audit = _ict_competency_audit(
                    [
                        db.get(Course, course_id)
                        for course_id in final_course_ids
                        if db.get(Course, course_id) is not None
                    ],
                    constraints,
                )
                if not final_audit.get("missing"):
                    break

    # Late competency, admission and semester repairs above can replace a
    # same-credit course with a different scoped candidate and, in an
    # interdisciplinary plan, leave a small residual overage.  Enforce the
    # exact target at the true end of the pipeline before validation; the
    # bounded trimmer only flexes bridge credits or removes whole non-critical
    # real-course units and never rewrites repository course credits.
    schedule = _trim_schedule_to_target_credits(schedule, target_credits, db)
    # The competency guard and the final credit trim may replace/remove a
    # same-credit secondary-domain course.  Quota repair must therefore be
    # the last schedule mutation before validation; otherwise a valid quota
    # can regress between repair and verification (notably ict-medicine A).
    trace("domain_repair_deferred_2")

    # Domain-quota repair is the last schedule mutation and may replace the
    # only real course carrying an ICT competency block. Restore that block at
    # the true validation boundary so no later balancing pass can erase it.
    if competency_requirements:
        final_course_ids = {
            int(item["course_id"])
            for rows in schedule.values()
            for item in rows
            if item.get("course_id") is not None
        }
        final_courses = {
            course.id: course
            for course in db.query(Course).options(selectinload(Course.prerequisites)).filter(
                Course.id.in_(final_course_ids or {-1})
            ).all()
        }
        final_audit = _ict_competency_audit(list(final_courses.values()), constraints)
        if final_audit.get("missing"):
            flat_items = [dict(item) for rows in schedule.values() for item in rows]
            repaired_items = _repair_missing_ict_competencies(
                flat_items, project_version, db, variant_type
            )
            repaired_by_id = {
                int(item["course_id"]): item
                for item in repaired_items
                if item.get("course_id") is not None
                and int(item["course_id"]) not in final_course_ids
                and item.get("competency_required")
            }
            if repaired_by_id:
                repaired_iter = iter(repaired_items)
                for semester, rows in schedule.items():
                    for index in range(len(rows)):
                        rows[index] = next(repaired_iter)
                schedule = _repair_semester_appropriateness(
                    schedule, num_semesters, nominal_load, db
                )
    trace("final_competency_boundary_done")

    # The final competency replacement can legitimately move a course to a
    # different semantic window. Re-establish the load envelope once more at
    # the actual validation boundary; no later mutation follows this pass.
    schedule = _repair_underloaded_semesters_with_bridges(
        schedule, project_version, nominal_load, target_credits, maximum_credits, db
    )
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)

    # Late semester/load repairs may introduce a bridge after the flat
    # selection cap above. Re-apply the same budget at the actual validation
    # boundary, while preserving each item's semester and all real courses.
    # This prevents an apparently valid plan from persisting 8+ bridge rows
    # when the interdisciplinary contract allows only seven.
    flat_schedule_items = [
        item for items in schedule.values() for item in items
    ]
    capped_items = _cap_bridge_items_to_budget(
        flat_schedule_items, project_version, confirmed_bridge_ids
    )
    capped_ids = {id(item) for item in capped_items}
    schedule = {
        semester: [
            item for item in items
            if item.get("bridge_module_id") is None or id(item) in capped_ids
        ]
        for semester, items in schedule.items()
    }
    trace("final_bridge_budget_done")
    # Removing an over-budget bridge can leave a small credit/load gap. Close
    # it only through the bounded repair path, which flexes retained bridges
    # before considering a new module and therefore cannot reintroduce the
    # bridge-count violation at this final boundary.
    schedule = _fill_schedule_credit_gap(
        schedule, project_version, target_credits, maximum_credits, db,
        real_candidates=selected_courses,
    )
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    # Credit-gap/load balancing can add or move a secondary-domain bridge.
    # Reconcile the domain quota at the true validation boundary so the
    # verifier sees the same invariant that the repair stage established.
    is_kz_regulatory = (
        str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() == "KZ"
    )
    # The later regulatory rebuild changes the schedule shape, but the first
    # quota repair is still required: it preserves real domain courses that
    # provide professional LO evidence before that rebuild. The final KZ pass
    # below validates the reconstructed schedule again.
    schedule = _repair_final_domain_quotas(
        schedule,
        domain_repair_candidates,
        project_version,
        db,
        is_admissible=is_project_domain,
    )
    # Domain replacement can change the credit weight of the affected
    # semester. Balance only after the last replacement; otherwise the
    # verifier can reject a plan that was balanced immediately beforehand.
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    schedule = _strict_rebalance_max_load(schedule, num_semesters, nominal_load + 3)
    trace("final_domain_quota_done")

    # Final regulatory boundary.  Several late quality repairs legitimately
    # replace ordinary courses, but none of them may be allowed to erase a
    # mandatory ГОСО component.  Rebuild the schedule from the current items
    # plus the canonical ruleset block, then trim only non-regulatory courses
    # as whole units to the requested total.  This is deliberately explicit:
    # the verifier must validate the same mandatory block that is persisted.
    if is_kz_regulatory:
        final_items = [item for rows in schedule.values() for item in rows]
        # Domain repair may have replaced an evidence-bearing professional
        # course. Re-run the existing evidence-backed LO repair at this final
        # boundary; it only admits scored in-scope EPVO rows and never uses a
        # synthetic bridge as proof of a real course outcome.
        final_items = _normalize_selected_courses_for_quality(
            final_items, project_version, db, variant_type
        )
        final_items = merge_goso_items(final_items, project_version, db)
        final_items = _trim_to_target_credits(final_items, target_credits, db)
        schedule = schedule_courses(final_items, num_semesters, nominal_load, db)
        # The regulatory block is not part of a project-domain quota.  Re-run
        # the quota repair against the complete post-GOSO schedule so a late
        # trim cannot leave one declared domain at zero.
        schedule = _repair_final_domain_quotas(
            schedule,
            domain_repair_candidates,
            project_version,
            db,
            is_admissible=is_project_domain,
        )
        final_items = [item for rows in schedule.values() for item in rows]
        final_items = merge_goso_items(final_items, project_version, db)
        final_items = _trim_to_target_credits(final_items, target_credits, db)
        schedule = schedule_courses(final_items, num_semesters, nominal_load, db)
    trace("regulatory_finalization_done")

    # The KZ regulatory branch performs its own final merge/trim/schedule
    # sequence.  Rebalance after that branch as well, at the actual verifier
    # boundary, so the last mutation cannot reintroduce a semester-load error.
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    trace("final_credit_rebalance_done")

    # The KZ branch rebuilds the schedule after quota repair and can erase a
    # previously closed credit gap.  Restore the exact credit contract at the
    # actual verifier boundary, before any publication decision is made.
    schedule = _fill_schedule_credit_gap(
        schedule, project_version, target_credits, maximum_credits, db,
        real_candidates=selected_courses,
    )
    # Credit filling may move an introductory bridge past its permitted
    # semester window. Restore that window after the last rebuild/fill, at
    # the actual verifier boundary.
    schedule = _relocate_bounded_bridges(schedule, num_semesters, nominal_load, db)
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    # A bounded bridge move can fill an early semester and leave a late one
    # short. Reuse the two-hop hard-load repair at this same final boundary;
    # its prerequisite and semester checks also protect the displaced course.
    schedule = _strict_rebalance_max_load(schedule, num_semesters, nominal_load + 3)
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    # Regulatory reconstruction can discard the real courses that supplied a
    # doctoral ICT competency. Reuse the evidence-scored, credit-preserving
    # replacement on the *final* schedule, before quota repair (which protects
    # competency_required courses). Never count a synthetic bridge as proof.
    if competency_requirements:
        final_items = [item for rows in schedule.values() for item in rows]
        repaired_items = _repair_missing_ict_competencies(
            final_items, project_version, db, variant_type
        )
        if len(repaired_items) != len(final_items):
            raise ValueError("Competency repair changed the final plan size")
        repaired_iter = iter(repaired_items)
        schedule = {
            semester: [next(repaired_iter) for _ in rows]
            for semester, rows in schedule.items()
        }
        schedule = _repair_semester_appropriateness(
            schedule, num_semesters, nominal_load, db
        )
        schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
        schedule = _strict_rebalance_max_load(schedule, num_semesters, nominal_load + 3)
    # The KZ merge/trim rebuild above can undo an earlier domain replacement.
    # Reconcile once on the schedule that will actually be verified and
    # persisted; subsequent load balancing does not change course membership.
    schedule = _repair_final_domain_quotas(
        schedule,
        domain_repair_candidates,
        project_version,
        db,
        is_admissible=is_project_domain,
    )
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    schedule = _strict_rebalance_max_load(schedule, num_semesters, nominal_load + 3)
    schedule = repair_exact_real_credit_overage(
        schedule, project_version, db,
        is_admissible=is_project_domain,
        variant_type=variant_type,
    )

    # Keep the final domain decision in one auditable helper.  The local scan
    # above is retained temporarily for compatibility while the orchestration
    # function is being split into pipeline phases; this assignment makes the
    # extracted boundary authoritative for the error raised below.
    boundary_audit = audit_final_schedule_boundary(
        schedule,
        db=db,
        project_version=project_version,
        project_domains=project_domains,
        declared_secondary_domain=declared_secondary_domain,
        is_project_domain=is_project_domain,
        is_general_course=lambda course: _course_curriculum_role(course, project_domains) == "general",
    )
    trace("publication_boundary_audit_done")
    invalid_domain_courses = boundary_audit["invalid_domain_courses"]
    if invalid_domain_courses:
        raise ValueError(
            "Planner selected courses outside the project domains: "
            + ", ".join(f"{c['title']} ({c['domain']})" for c in invalid_domain_courses[:8])
        )
    admission_audit = boundary_audit["admission"]
    if not admission_audit["passed"]:
        examples = admission_audit["violations"][:8]
        late_schedule = late_schedule_snapshot(
            schedule,
            db=db,
            num_semesters=num_semesters,
            minimum_semester=_minimum_appropriate_semester,
        )
        raise ValueError(
            "Admission filter rejected real courses: "
            + ", ".join(
                (
                    f"{row.get('title')} [{row.get('reason')}; "
                    f"semester={row.get('semester')}; "
                    f"minimum={row.get('minimum_semester')}; "
                    f"source={row.get('selection_method')}]"
                )
                for row in examples
            )
            + f"; late_schedule={late_schedule}"
        )
    verification = verify_curriculum_plan(schedule, project_version, db)
    trace("verification_done")
    verification["prerequisite_graph"] = prerequisite_graph
    metrics = calculate_plan_metrics(schedule, selected_courses, project_version, db, verification)
    metrics["invariant_ledger"] = invariant_ledger.as_dict()
    if str((project_version.project.constraints_json or {}).get("jurisdiction") or "INTERNATIONAL").upper() == "KZ":
        from app.planner.goso_ruleset import GOSO_RULESET_CHECKSUM, GOSO_RULESET_VERSION
        metrics["goso_ruleset_version"] = GOSO_RULESET_VERSION
        metrics["goso_ruleset_checksum"] = GOSO_RULESET_CHECKSUM
        metrics["goso_ruleset_source"] = "https://adilet.zan.kz/rus/docs/V2200028916"
    metrics["course_admission"] = admission_audit
    # Persist compact evidence at the publication boundary.  Later rescoring
    # may improve the catalogue, but must not rewrite why an older plan chose
    # these particular disciplines.
    metrics["selection_evidence_snapshot"] = build_selection_evidence_snapshot(
        schedule, project_version_id, db
    )
    trace("plan_ready")
    return persist_plan_result(
        db=db,
        project_version_id=project_version_id,
        variant_type=variant_type,
        schedule=schedule,
        metrics=metrics,
        verification=verification,
        commit=commit,
    )
