from __future__ import annotations

from typing import Dict, List
from itertools import combinations
import math
import re
from statistics import median
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.bridge_module import BridgeModule
from app.models.course import Course, course_prerequisites
from app.models.embedding import MatchScore
from app.models.plan import Plan, PlanItem
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
from app.planner.bridge_policy import bridge_module_limit
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
from app.planner.course_scheduling import schedule_courses
from app.planner.scheduler_domain_rules import (
    course_domain_matches as _course_domain_matches,
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
from app.planner.admission import (
    audit_final_course_admission as _audit_final_course_admission,
    credible_professional_lo_by_course as _credible_professional_lo_by_course,
    minimum_appropriate_semester as _minimum_appropriate_semester,
)


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
) -> Dict:
    project_version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    if not project_version:
        raise ValueError(f"Project version {project_version_id} not found")
    constraints = project_version.project.constraints_json or {}
    excluded_course_ids = {
        int(value) for value in (constraints.get("excluded_course_ids") or [])
        if str(value).isdigit()
    }
    selected_courses = select_courses_for_variant(project_version_id, db, variant_type)
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
        selected_courses, project_version, db
    )
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
            *ensure_secondary_domain_bridge_modules(project_version, db),
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

    def is_project_domain(course: Course) -> bool:
        if course.id in excluded_course_ids:
            return False
        if not _education_level_course_allowed(course, constraints.get("education_level")):
            return False
        # Canonical EPVO rows can retain the domain of their first source
        # programme after title deduplication.  Never let a medical row enter
        # an ICT+agriculture plan merely because a broad alias/scope match
        # succeeded elsewhere in the pipeline.
        course_domain_key = str(course.domain or "").casefold()
        project_domain_text = " ".join(project_domains).casefold()
        medical_domain = any(token in course_domain_key for token in ("medicine", "medical", "health", "медицин", "здрав", "clinical"))
        medical_project = any(token in project_domain_text for token in ("medicine", "medical", "health", "медицин", "здрав", "clinical"))
        agriculture_project = any(token in f"{declared_secondary_domain} {project_domain_text}" for token in ("agri", "agro", "farm", "сельск", "аграр", "агроном", "ауыл"))
        declared_medical_project = any(token in declared_secondary_domain for token in ("medicine", "medical", "health", "медицин", "здрав", "clinical"))
        if medical_domain and agriculture_project and not declared_medical_project:
            return False
        if not (
            _course_domain_matches(course, project_domains)
            or domain_label_matches(course.domain, project_domains)
        ):
            return False
        if cyber_forensics_program:
            return _course_curriculum_role(course, project_domains) == "core"
        if interdisciplinary_professional and _course_curriculum_role(course, project_domains) == "general":
            return match_max_by_course.get(course.id, 0.0) >= 0.55
        return True

    def sanitize_selected_courses(items: List[Dict]) -> List[Dict]:
        """Prevent late credit/prerequisite repair from bypassing admission."""
        cleaned = []
        for item in items:
            if item.get("regulatory_required"):
                cleaned.append(item)
                continue
            course_id = item.get("course_id")
            if course_id is None:
                cleaned.append(item)
                continue
            course = db.get(Course, course_id) if course_id else None
            if course is None:
                continue
            code = str(course.course_id or "")
            if code.startswith("GOSO-KZ-") and str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() == "KZ":
                item["regulatory_required"] = True
                cleaned.append(item)
                continue
            if not item.get("admission_los"):
                continue
            if not _education_level_course_allowed(course, constraints.get("education_level")):
                continue
            if course and _course_curriculum_role(course, project_domains) == "general":
                if match_max_by_course.get(course.id, 0.0) < 0.55:
                    continue
            cleaned.append(item)
        return cleaned

    selected_courses = sanitize_selected_courses(selected_courses)
    selected_courses = _trim_to_target_credits(selected_courses, target_credits, db)
    # Final candidate repairs can reintroduce a second generic foundation
    # after the earlier normalization pass.  Deduplicate once immediately
    # before scheduling so a late duplicate cannot create a false semester
    # violation or consume professional-course capacity.
    selected_courses = _unique_items_by_title(selected_courses)
    selected_courses = _apply_scoped_epvo_semesters(selected_courses, project_version, db)

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
            selected_courses, project_version, db
        )
        schedule = schedule_courses(selected_courses, num_semesters, nominal_load, db)
        schedule = _relocate_bounded_bridges(schedule, num_semesters, nominal_load, db)
        verification = verify_curriculum_plan(schedule, project_version, db)
        offending = {item["course_id"] for item in verification["prerequisite_violations"] if item.get("course_id") is not None}
        if not offending: break
        selected_courses = [item for item in selected_courses if item.get("course_id") not in offending]
        selected_ids = {item.get("course_id") for item in selected_courses if item.get("course_id") is not None}
        total = sum(item.get("credits") or 0 for item in selected_courses)
        replacements = [
            course for course in db.query(Course).filter(
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
        selected_courses, project_version, db
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
            and int(item.get("credits") or 0) == 5
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
        residual_courses = {
            course.id: course
            for course in db.query(Course).filter(
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
        if residual_candidates:
            real_fill = dict(residual_candidates[0])
            real_fill["selection_method"] = "final_real_credit_fill"
            selected_courses.append(real_fill)

    selected_courses = _apply_scoped_epvo_semesters(selected_courses, project_version, db)
    schedule = schedule_courses(selected_courses, num_semesters, nominal_load, db)
    schedule = _relocate_bounded_bridges(schedule, num_semesters, nominal_load, db)
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
                target_los=[lo.lo_code for lo in project_version.learning_outcomes],
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
    schedule = _repair_underloaded_semesters_with_bridges(
        schedule, project_version, nominal_load, target_credits, maximum_credits, db
    )
    # Flexible bridge credits can change by one during residual repair. Run
    # the bounded whole-course/swap balancer once more so a valid 3↔4 credit
    # exchange is not left as a 26-credit semester.
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    # The residual-load repair is intentionally the last credit operation, but
    # it can change which semester has room for a foundation course.  Re-run
    # the semantic repair so the persisted plan, not only the provisional
    # schedule, satisfies the same semester bounds as the verifier.
    schedule = _repair_semester_appropriateness(
        schedule, num_semesters, nominal_load, db
    )
    schedule = _repair_final_domain_quotas(
        schedule, domain_repair_candidates, project_version, db
    )
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
        schedule, project_version, target_credits, maximum_credits, db
    )
    schedule = _rebalance_semester_load(schedule, num_semesters, nominal_load)
    schedule = _strict_rebalance_max_load(schedule, num_semesters, nominal_load + 3)
    # Rebalancing can expose a residual gap after the first bridge repair.
    # Run the bounded repair once more at the final envelope; no later step
    # removes these explicit bridge credits.
    schedule = _fill_schedule_credit_gap(
        schedule, project_version, target_credits, maximum_credits, db
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
            for course in db.query(Course).filter(
                Course.id.in_(final_course_ids or {-1})
            ).all()
        }
        final_audit = _ict_competency_audit(list(final_courses.values()), constraints)
        if final_audit.get("missing"):
            flat_items = [dict(item) for rows in schedule.values() for item in rows]
            repaired_items = _repair_missing_ict_competencies(
                flat_items, project_version, db
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

    invalid_domain_courses = []
    for semester_items in schedule.values():
        for item in semester_items:
            if item.get("regulatory_required"):
                continue
            course_id = item.get("course_id")
            if course_id is None:
                continue
            course = db.get(Course, course_id)
            item_domain = str(item.get("domain") or "").lower().strip()
            raw_course_domain = str(course.domain or "").casefold() if course else ""
            if course and raw_course_domain.startswith(("med", "health", "мед", "здрав")) and not any(
                token in f"{declared_secondary_domain} {' '.join(project_domains)}"
                for token in ("medicine", "medical", "health", "медицин", "здрав", "clinical")
            ):
                continue
            declared_agriculture = any(
                token in f"{declared_secondary_domain} {' '.join(project_domains)}"
                for token in ("agri", "agro", "farm", "сельск", "аграр", "агроном", "ауыл")
            )
            canonical_domain = str(course.domain or "").casefold() if course else ""
            item_medical = any(token in f"{item_domain} {canonical_domain}" for token in ("medicine", "medical", "health", "медицин", "здрав", "clinical"))
            project_has_medical_domain = any(
                token in f"{declared_secondary_domain} {' '.join(project_domains)}"
                for token in ("medicine", "medical", "health", "медицин", "здрав", "clinical")
            )
            canonical_medical = canonical_domain in {"medicine", "medical", "health sciences", "здравоохранение"}
            if (declared_agriculture and (item_medical or canonical_medical)) or ((item_medical or canonical_medical) and not project_has_medical_domain):
                invalid_domain_courses.append({"course_id": course.id, "title": course.title, "domain": course.domain})
                continue
            item_has_project_domain = any(
                domain and (domain in item_domain or item_domain in domain)
                for domain in project_domains
            ) or domain_label_matches(item_domain, project_domains)
            # The selector rewrites canonical EPVO labels to the exact
            # project-specific direction. Trust that evidence here; canonical
            # Course.domain may come from the first programme that used the
            # deduplicated discipline (for example, "Medicine").
            if course and not (is_project_domain(course) or item_has_project_domain):
                if (canonical_medical or canonical_domain.startswith(("med", "health", "мед", "здрав"))) and not project_has_medical_domain:
                    continue
                invalid_domain_courses.append({
                    "course_id": course.id,
                    "title": course.title,
                    "domain": course.domain,
                })
    if invalid_domain_courses:
        raise ValueError(
            "Planner selected courses outside the project domains: "
            + ", ".join(f"{c['title']} ({c['domain']})" for c in invalid_domain_courses[:8])
        )
    admission_audit = _audit_final_course_admission(schedule, project_version, db)
    if not admission_audit["passed"]:
        examples = admission_audit["violations"][:8]
        late_schedule = {
            int(semester): {
                "credits": sum(
                    int(item.get("credits") or 0) for item in items
                ),
                "items": [
                    {
                        "title": item.get("title"),
                        "credits": int(item.get("credits") or 0),
                        "minimum": (
                            _minimum_appropriate_semester(
                                item,
                                db.get(Course, int(item["course_id"])),
                                num_semesters,
                            )
                            if item.get("course_id") is not None
                            and db.get(Course, int(item["course_id"])) is not None
                            else None
                        ),
                        "regulatory": bool(item.get("regulatory_required")),
                        "competency": bool(item.get("competency_required")),
                    }
                    for item in items
                ],
            }
            for semester, items in schedule.items()
            if int(semester) >= max(1, num_semesters - 2)
        }
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
    verification["prerequisite_graph"] = prerequisite_graph
    metrics = calculate_plan_metrics(schedule, selected_courses, project_version, db, verification)
    metrics["course_admission"] = admission_audit
    plan = Plan(project_version_id=project_version_id, variant_type=variant_type, metrics_json=metrics)
    db.add(plan); db.flush()
    for semester, courses in schedule.items():
        for item in courses:
            db.add(PlanItem(plan_id=plan.id, semester=semester, course_id=item.get("course_id"), bridge_module_id=item.get("bridge_module_id"), credits=item["credits"], course_type=item.get("type", "mandatory"), prerequisites_snapshot=item.get("prerequisites", [])))
    if commit:
        db.commit()
        db.refresh(plan)
    else:
        db.flush()
    semester_los = {}
    semester_lo_details = {}
    lo_by_id = {
        lo.id: lo
        for lo in db.query(LearningOutcome)
        .filter(LearningOutcome.project_version_id == project_version_id)
        .all()
    }
    lo_by_code = {lo.lo_code: lo for lo in lo_by_id.values()}
    for semester, courses in schedule.items():
        evidence = {}
        for item in courses:
            if item.get("course_id"):
                all_rows = db.query(MatchScore).filter(
                    MatchScore.course_id == item["course_id"],
                    MatchScore.project_version_id == project_version_id,
                ).order_by(MatchScore.score.desc()).all()
                rows = [row for row in all_rows if row.score >= 0.4] or all_rows[:1]
                for row in rows:
                    lo = lo_by_id.get(row.lo_id)
                    if lo:
                        detail = evidence.setdefault(lo.lo_code, {
                            "code": lo.lo_code,
                            "text": lo.lo_text,
                            "score": 0.0,
                            "courses": [],
                            "kind": "programme",
                        })
                        detail["score"] = max(detail["score"], round(float(row.score), 3))
                        if item.get("title") not in detail["courses"]:
                            detail["courses"].append(item.get("title"))
            elif item.get("bridge_module_id"):
                bridge = db.query(BridgeModule).filter(BridgeModule.id == item["bridge_module_id"]).first()
                for code in (bridge.target_los or []) if bridge else []:
                    lo = lo_by_code.get(code)
                    if lo:
                        detail = evidence.setdefault(code, {
                            "code": code,
                            "text": lo.lo_text,
                            "score": 0.75,
                            "courses": [],
                            "kind": "programme",
                        })
                        detail["score"] = max(detail["score"], 0.75)
                        if item.get("title") not in detail["courses"]:
                            detail["courses"].append(item.get("title"))
        details = sorted(evidence.values(), key=lambda row: row["code"])
        semester_lo_details[semester] = details
        semester_los[semester] = ", ".join(row["code"] for row in details) if details else "-"
    return {"plan_id": plan.id, "variant_type": variant_type, "schedule": schedule, "metrics": metrics, "verification": verification, "semester_los": semester_los, "semester_lo_details": semester_lo_details}












def _cap_bridge_items_to_budget(
    selected_courses: List[Dict],
    project_version: ProjectVersion,
    confirmed_bridge_ids: set[int] | None = None,
) -> List[Dict]:
    """Keep bridge units within the auditable programme budget.

    Bridge rows may be introduced by several independent repair stages.  A
    single final gate prevents those stages from accumulating 10+ modules.
    Confirmed replacements are retained; remaining slots favour bridges with
    more explicit LO targets and higher admission evidence.
    """
    limit = bridge_module_limit(project_version)
    bridges = [item for item in selected_courses if item.get("bridge_module_id") is not None]
    if len(bridges) <= limit:
        return selected_courses
    confirmed = confirmed_bridge_ids or set()
    protected = [item for item in bridges if int(item.get("bridge_module_id") or 0) in confirmed]
    if len(protected) >= limit:
        protected.sort(
            key=lambda item: (
                0 if str(item.get("course_id") or "").startswith("SECONDARY_INTEGRATION_") else
                1 if str(item.get("course_id") or "").startswith("SECONDARY_") else 2,
                -int(item.get("credits") or 0),
            )
        )
        keep = protected[:limit]
    else:
        remaining = [item for item in bridges if item not in protected]
        remaining.sort(
            key=lambda item: (
                # Preserve explicit interdisciplinary structure before
                # generic LO-gap/load-repair bridges.  Without this priority
                # the cap kept SECONDARY_FOUNDATION/DATA/ADVANCED but dropped
                # SECONDARY_INTEGRATION, making the second-domain quota fail.
                0 if str(item.get("course_id") or "").startswith("SECONDARY_INTEGRATION_") else
                1 if str(item.get("course_id") or "").startswith("SECONDARY_") else 2,
                -len(item.get("target_los") or item.get("learning_outcomes") or []),
                -float(item.get("admission_score") or item.get("score") or 0.0),
                int(item.get("credits") or 0),
            )
        )
        keep = protected + remaining[: max(0, limit - len(protected))]
    keep_ids = {id(item) for item in keep}
    return [
        item for item in selected_courses
        if item.get("bridge_module_id") is None or id(item) in keep_ids
    ]


def _fill_schedule_credit_gap(
    schedule: Dict[int, List[Dict]],
    project_version: ProjectVersion,
    target_credits: int,
    maximum_credits: int,
    db: Session,
) -> Dict[int, List[Dict]]:
    """Close a residual schedule gap after late semester repairs."""
    total = sum(int(item.get("credits") or 0) for items in schedule.values() for item in items)
    gap = int(target_credits) - total
    if gap <= 0:
        return schedule
    # Prefer flexing existing bridges before creating another visible module.
    for items in schedule.values():
        for item in reversed(items):
            if gap <= 0 or item.get("bridge_module_id") is None:
                continue
            room = min(7 - int(item.get("credits") or 0), gap)
            if room <= 0:
                continue
            item["credits"] = int(item.get("credits") or 0) + room
            module = db.query(BridgeModule).filter(BridgeModule.id == item["bridge_module_id"]).first()
            if module:
                module.credits = item["credits"]
            gap -= room
    if gap <= 0:
        return schedule
    if total + gap > int(maximum_credits):
        return schedule
    # Late prerequisite/domain repairs can remove several real courses after
    # the earlier bridge-slot pass.  Creating only one module here left new
    # programmes at 120--151/240 credits even though the planner was allowed
    # to use explicit bridge modules.  Close the residual gap atomically with
    # the minimum number of 3--7 credit modules instead of silently returning
    # an incomplete plan.  The verifier still marks bridge-heavy plans for
    # expert review; this change only makes the credit envelope deterministic.
    existing_bridge_ids = {
        int(item.get("bridge_module_id"))
        for items in schedule.values()
        for item in items
        if item.get("bridge_module_id") is not None
    }
    available_bridge_slots = max(
        0, bridge_module_limit(project_version) - len(existing_bridge_ids)
    )
    if available_bridge_slots <= 0:
        return schedule
    slots_needed = min(available_bridge_slots, max(1, math.ceil(gap / 7)))
    modules = ensure_credit_bridge_modules(
        project_version,
        db,
        gap,
        slots_needed,
        desired_count=slots_needed,
    )
    if not modules:
        return schedule
    remaining = gap
    for module in modules:
        if remaining <= 0:
            break
        module.credits = max(3, min(7, math.ceil(remaining / max(1, len(modules)))) )
        item = _bridge_item(module)
        item["credits"] = module.credits
        upper = int((project_version.project.constraints_json or {}).get(
            "max_credits_per_semester", 30
        )) + 3
        eligible = [
            value for value in schedule
            if sum(int(row.get("credits") or 0) for row in schedule[value]) + int(item["credits"]) <= upper
        ]
        if not eligible:
            break
        semester = min(
            eligible,
            key=lambda value: sum(int(row.get("credits") or 0) for row in schedule[value]),
        )
        schedule[semester].append(item)
        remaining -= module.credits
    return schedule
