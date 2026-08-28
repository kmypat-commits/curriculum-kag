from __future__ import annotations

from functools import partial
from itertools import combinations
import heapq
import math
from typing import Dict, List

from sqlalchemy.orm import Session

from app.config import settings
from app.models.bridge_module import BridgeModule
from app.models.course import Course, course_prerequisites
from app.models.embedding import MatchScore
from app.models.plan import Plan, PlanItem
from app.models.project import LearningOutcome, ProjectVersion
from app.planner.admission import (
    admit_real_course_items as _admit_real_course_items,
    audit_final_course_admission as _audit_final_course_admission,
    credible_professional_lo_by_course as _credible_professional_lo_by_course,
    minimum_appropriate_semester as _minimum_appropriate_semester,
)
from app.planner.course_policy import (
    course_curriculum_role as _course_curriculum_role,
    course_role_rank as _course_role_rank,
    education_level_course_allowed as _education_level_course_allowed,
    project_domain_terms as _project_domain_terms,
)
from app.planner.domain_evidence import domain_label_matches
from app.planner.goso import merge_goso_items
from app.planner.scheduler_catalogue import (
    foundation_equivalent_title_key as _foundation_equivalent_title_key,
    is_component_placeholder_title as _is_component_placeholder_title,
    unique_items_by_title as _unique_items_by_title,
)
from app.planner.scheduler_domain_rules import (
    course_domain_matches as _course_domain_matches,
    has_foreign_professional_title as _has_foreign_professional_title,
    is_interdisciplinary_title_relevant as _is_interdisciplinary_title_relevant,
    is_it_medicine_support_course as _is_it_medicine_support_course,
    invalid_project_domain_label as _is_invalid_project_domain_label,
)
from app.planner.scheduler_text import (
    has_domain_term as _has_domain_term,
    short_lo_theme as _short_lo_theme,
)
from app.planner.scheduler_utils import title_key as _title_key
from app.planner.semester_rules import (
    complexity_min_semester as _complexity_min_semester,
    cycle_min_semester as _cycle_min_semester,
    foundation_max_semester as _foundation_max_semester,
    late_stage_min_semester as _late_stage_min_semester,
    minimum_appropriate_semester as _item_minimum_appropriate_semester,
)
from app.planner.verifier import (
    TOTAL_CREDIT_TOLERANCE,
    _ict_competency_audit,
    _ict_competency_requirements,
    verify_curriculum_plan,
)
from app.services.epvo_repository import epvo_row_matches_education_level

from app.planner.bridge_creation import (
    _bridge_item,
    _ensure_foundation_capacity,
    _fill_existing_bridge_credit_gap,
    _force_bridge_item,
    _trim_to_target_credits,
    ensure_credit_bridge_modules,
    ensure_core_interdisciplinary_bridge,
    ensure_secondary_domain_bridge_modules,
)
from app.planner.bridge_policy import bridge_module_limit
from app.planner.candidate_retrieval import (
    _fit_real_professional_block_after_goso,
    _limit_general_course_items,
    _normalize_selected_courses_for_quality,
    _promote_epvo_priority_courses,
    _remap_equivalent_prerequisites,
    _repair_missing_ict_competencies,
    _select_exact_professional_subset,
)
from app.planner.variant_assembly import (
    add_bundle_if_fits,
    assemble_foundation_frontier,
    build_prerequisite_bundle,
    selected_domain_credits,
    top_up_with_real_epvo_courses as _top_up_with_real_epvo_courses,
)
from app.planner.variant_admission import (
    is_project_domain_course as _is_project_domain_course,
    remove_weak_general_items as _remove_weak_general_items,
)
from app.planner.variant_prerequisites import (
    filter_supported_prerequisites,
    make_course_depth,
)
from app.planner.variant_ranking import (
    get_domain_quota_candidates,
    rank_admissible_frontier,
    variant_candidate_key,
)
from app.planner.variant_scope import build_epvo_scope_index
from app.planner.variant_quota import (
    build_missing_domain_bundle as _build_missing_domain_bundle,
    credits_by_domain as _credits_by_domain,
    protected_quota_course_ids as _protected_quota_course_ids,
    quality_preserved_after_swap as _quality_preserved_after_swap,
    required_domain_credits as _required_domain_credits,
)
from app.planner.variant_repairs import top_up_with_credit_bridges as _top_up_with_credit_bridges
from app.planner.variant_coverage import (
    coverage_objective as _coverage_objective,
    coverage_state as _coverage_state,
)
from app.planner.variant_lo_repair import close_professional_lo_gaps as _close_professional_lo_gaps
from app.planner.variant_domain_repair import (
    rebalance_domain_quotas as _rebalance_domain_quotas,
    reserve_domain_quota as _reserve_domain_quota,
)
from app.planner.variant_diversification import _diversify_variant_items
from app.planner.variant_replacements import (
    apply_confirmed_variant_replacements,
    replace_redundant_bridges_with_real_courses as _replace_redundant_bridges,
)
from app.planner.variant_policy import (
    course_matches_scope_theme as _policy_course_matches_scope_theme,
    foreign_scope_conflict as _policy_foreign_scope_conflict,
    priority_rank as _policy_priority_rank,
    project_domain_index as _policy_project_domain_index,
    project_domain_share as _policy_project_domain_share,
    role_rank as _policy_role_rank,
    scope_rank as _policy_scope_rank,
    semester_stability_rank as _policy_semester_stability_rank,
    strong_exact_scope_evidence as _policy_strong_exact_scope_evidence,
)

def select_courses_for_variant(project_version_id: int, db: Session, variant_type: str) -> List[Dict]:
    version = db.query(ProjectVersion).filter(ProjectVersion.id == project_version_id).first()
    constraints = version.project.constraints_json or {}
    target = int(constraints.get("total_credits", 240)); maximum = target + max(0, int(constraints.get("credit_tolerance", TOTAL_CREDIT_TOLERANCE)))
    project_domains = _project_domain_terms(version, db)
    program_type = str(constraints.get("program_type") or "standard").lower()
    interdisciplinary = program_type in {"interdisciplinary", "joint"} and bool(project_domains[1])
    # Integration bridges represent the connection between two independently
    # selected fields.  Forcing them into a standard one-field programme used
    # to replace valid EPVO courses with five synthetic modules.
    allow_bridges = bool(constraints.get("allow_new_courses", True))
    core_bridge = ensure_core_interdisciplinary_bridge(version, db) if allow_bridges and interdisciplinary else None
    secondary_bridges = ensure_secondary_domain_bridge_modules(version, db) if allow_bridges and interdisciplinary else []
    cyber_forensics_program = (
        any("it" in d or "информ" in d or "computer" in d or "кибер" in d for d in project_domains)
        and any("forensic" in d or "криминал" in d or "расслед" in d for d in project_domains)
    )
    interdisciplinary_professional = interdisciplinary
    epvo_professional_scope = any(
        str(constraints.get(key) or "").strip() not in {"", "1", "none", "null"}
        for key in ("group_code", "direction_code", "secondary_group_code", "secondary_direction_code")
    )
    professional_scope = interdisciplinary_professional or epvo_professional_scope or cyber_forensics_program
    default_general_percent = 5 if cyber_forensics_program else 8 if interdisciplinary_professional else 20
    max_general_percent = int(constraints.get("max_general_percent", default_general_percent) or default_general_percent)
    quota_total_credits = int(constraints.get("total_credits", target))
    min_domain_percent = [
        max(0, int(constraints.get("min_domain1_percent") or 0)),
        max(0, int(constraints.get("min_domain2_percent") or 0)) if interdisciplinary else 0,
    ]
    epvo_domain_index: Dict[int, int] = {}
    epvo_domain_shares: Dict[int, tuple[float, float]] = {}
    # Filled from normalized EPVO rows that match both the selected scope and
    # the programme education level. A high semantic score must never allow a
    # bachelor-only catalogue card into a master's/doctoral curriculum.
    epvo_level_scope_allowed_ids: set[int] = set()

    min_general_lo_evidence = 0.55
    # The optimized NSGA-II branch is evaluated before the deterministic
    # catalogue top-up helper is declared below.  Use a safe no-op callback
    # until that helper is bound, rather than resolving an unbound local name.
    top_up_real_epvo_callback = lambda values: values

    def top_up_with_credit_bridges(items: List[Dict]) -> List[Dict]:
        return _top_up_with_credit_bridges(
            items,
            allow_new_courses=bool(constraints.get("allow_new_courses", True)),
            target=target,
            maximum=maximum,
            # Preserve an explicit zero: standard/GOSO profiles may forbid
            # synthetic bridge courses entirely.  Using ``or 5`` silently
            # converted that policy into a five-course bridge budget.
            max_new_courses=max(0, int(constraints.get("max_new_courses", 5) or 0)),
            variant_type=variant_type,
            version=version,
            db=db,
            top_up_real_epvo_callback=top_up_real_epvo_callback,
            ensure_credit_bridge_modules=ensure_credit_bridge_modules,
            bridge_item=_bridge_item,
        )

    def close_professional_lo_gaps(items: List[Dict]) -> List[Dict]:
        # Dependencies are resolved when the wrapper is called, after the
        # scope, catalogue and prerequisite indexes have been built below.
        return _close_professional_lo_gaps(
            items,
            professional_scope=professional_scope,
            version=version,
            db=db,
            project_version_id=project_version_id,
            courses=courses,
            constraints=constraints,
            project_domains=project_domains,
            aggregates=aggregates,
            prereq_ids_by_course=prereq_ids_by_course,
            scope_rank=scope_rank,
            priority_rank=priority_rank,
            is_project_domain=is_project_domain,
            variant_type=variant_type,
            coverage_threshold=float(settings.COVERAGE_THRESHOLD),
            unique_items_by_title=_unique_items_by_title,
            bridge_item=_bridge_item,
        )
    def project_domain_index(course: Course) -> int | None:
        return _policy_project_domain_index(course, project_domains, epvo_domain_index)

    def project_domain_share(course: Course | None, domain_index: int) -> float:
        """Return a course's non-duplicated contribution to one domain quota."""
        return _policy_project_domain_share(
            course, domain_index, epvo_domain_shares, project_domain_index
        )

    weights = {lo.id: lo.weight or 1.0 for lo in version.learning_outcomes}
    lo_codes_by_id = {lo.id: lo.lo_code for lo in version.learning_outcomes}
    aggregates: Dict[int, Dict] = {}
    for match in db.query(MatchScore).filter(MatchScore.project_version_id == project_version_id).all():
        data = aggregates.setdefault(match.course_id, {
            "sum": 0.0, "los": set(), "lo_codes": set(), "credible_lo_codes": set(),
            "professional_lo_codes": set(), "lo_scores": {}, "max": 0.0, "expert": 0.0,
        })
        data["sum"] += match.score * weights.get(match.lo_id, 1.0)
        data["los"].add(match.lo_id)
        if lo_codes_by_id.get(match.lo_id):
            data["lo_codes"].add(lo_codes_by_id[match.lo_id])
        expert_value = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        effective_value = max(float(match.score or 0.0), expert_value)
        lo_code = str(lo_codes_by_id.get(match.lo_id) or "")
        if lo_code:
            data["lo_scores"][lo_code] = max(
                float(data["lo_scores"].get(lo_code) or 0.0), effective_value
            )
        if lo_code and effective_value >= 0.4:
            data["credible_lo_codes"].add(lo_code)
            if not lo_code.startswith("LO-GOSO-"):
                data["professional_lo_codes"].add(lo_code)
        data["expert"] = max(data["expert"], expert_value)
        data["max"] = max(data["max"], effective_value)
    prereq_ids_by_course: Dict[int, List[int]] = {}
    for row in db.execute(course_prerequisites.select()).fetchall():
        prereq_ids_by_course.setdefault(int(row.course_id), []).append(int(row.prerequisite_id))
    eligible_course_ids = set(aggregates)
    if professional_scope:
        frontier = set(eligible_course_ids)
        for _ in range(2):
            next_frontier = {
                prerequisite_id
                for course_id in frontier
                for prerequisite_id in prereq_ids_by_course.get(course_id, [])
                if prerequisite_id not in eligible_course_ids
            }
            eligible_course_ids.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break
        local_prefix = f"AI-CONFIRMED-{project_version_id}-"
        eligible_course_ids.update(
            row[0] for row in db.query(Course.id).filter(Course.course_id.like(f"{local_prefix}%")).all()
        )
        course_query = db.query(Course).filter(Course.id.in_(eligible_course_ids or [-1]))
    else:
        course_query = db.query(Course)
    courses = {
        course.id: course for course in course_query.all()
        if not _is_component_placeholder_title(_title_key(course.title))
    }
    scope_index = build_epvo_scope_index(
        db,
        version=version,
        constraints=constraints,
        aggregates=aggregates,
        courses=courses,
        title_key=_title_key,
    )
    epvo_scope = scope_index.scope_by_title
    epvo_priority = scope_index.priority_by_title
    epvo_scope_by_id = scope_index.scope_by_course
    epvo_priority_by_id = scope_index.priority_by_course
    epvo_semester_values = scope_index.semester_values_by_course
    epvo_level_scope_allowed_ids = scope_index.level_scope_allowed_ids
    epvo_domain_index = scope_index.domain_index_by_course
    epvo_domain_shares = scope_index.domain_shares_by_course

    # In professional EPVO projects an unscored catalogue row cannot pass the
    # evidence guard. Keeping all ~20k repository courses in every repair and
    # quota loop only increases latency. Retain scored candidates, their
    # prerequisite closure, and project-local confirmed replacements.
    if professional_scope:
        prereq_ids_by_course = {
            course_id: [value for value in values if value in eligible_course_ids]
            for course_id, values in prereq_ids_by_course.items()
            if course_id in eligible_course_ids
        }

    def scope_rank(course: Course) -> int:
        return _policy_scope_rank(course, epvo_scope_by_id, epvo_scope)

    is_project_domain = partial(
        _is_project_domain_course,
        education_level=constraints.get("education_level"),
        professional_scope=professional_scope,
        project_domains=project_domains,
        interdisciplinary_professional=interdisciplinary_professional,
        cyber_forensics_program=cyber_forensics_program,
        epvo_professional_scope=epvo_professional_scope,
        project_version_id=project_version_id,
        epvo_level_scope_allowed_ids=epvo_level_scope_allowed_ids,
        epvo_domain_index=epvo_domain_index,
        aggregates=aggregates,
        min_general_lo_evidence=min_general_lo_evidence,
        education_level_allowed=_education_level_course_allowed,
        foreign_professional_title=_has_foreign_professional_title,
        medicine_support_course=_is_it_medicine_support_course,
        course_domain_matches=_course_domain_matches,
        domain_label_matches=domain_label_matches,
        curriculum_role=_course_curriculum_role,
        scope_rank=scope_rank,
    )
    remove_weak_general_items = partial(
        _remove_weak_general_items,
        professional_scope=professional_scope,
        courses=courses,
        project_domains=project_domains,
        aggregates=aggregates,
        curriculum_role=_course_curriculum_role,
        min_general_lo_evidence=min_general_lo_evidence,
    )

    def priority_rank(course: Course) -> int:
        return _policy_priority_rank(course, epvo_priority_by_id, epvo_priority)
    def semester_stability_rank(course: Course | None) -> float:
        """Prefer candidates whose scoped EPVO semester evidence is stable.

        This is deliberately a secondary rank component: LO evidence, expert
        support, scope and domain relevance remain dominant. A zero value means
        that no scoped semester evidence is available and therefore never
        penalizes a candidate by itself.
        """
        return _policy_semester_stability_rank(course, epvo_semester_values)
    def role_rank(course: Course | None) -> int:
        return _policy_role_rank(course, project_domains)

    domain_text = " ".join(project_domains).lower()
    ict_programme = any(marker in domain_text for marker in ("информац", "коммуникац", "it", "computer", "software", "digital", "кибер"))
    medical_programme = any(marker in domain_text for marker in ("медицин", "здрав", "clinical", "health"))
    agro_programme = any(marker in domain_text for marker in ("агро", "сельск", "растен", "почв"))

    def has_foreign_scope_conflict(course: Course) -> bool:
        return _policy_foreign_scope_conflict(course, domain_text)

    def course_matches_scope_theme(course: Course) -> bool:
        return _policy_course_matches_scope_theme(
            course, project_domains, domain_text, ict_programme, medical_programme, agro_programme
        )

    def has_strong_exact_scope_evidence(course: Course) -> bool:
        """Let exact EPVO group evidence override a shallow keyword mismatch."""
        return _policy_strong_exact_scope_evidence(
            course, aggregates, scope_rank, domain_text
        )

    admit_real_courses = partial(
        _admit_real_course_items,
        constraints=constraints,
        courses=courses,
        aggregates=aggregates,
        scope_rank=scope_rank,
        is_project_domain=is_project_domain,
        course_matches_scope_theme=course_matches_scope_theme,
        has_strong_exact_scope_evidence=has_strong_exact_scope_evidence,
    )

    raw_prereq_ids_by_course = prereq_ids_by_course
    generic_prerequisite_terms = {
        "основ", "введен", "систем", "метод", "технолог", "управлен", "анализ",
        "соврем", "дисциплин", "course", "system", "method", "technology", "management",
    }
    num_semesters = int(constraints.get("total_semesters", 8))
    # The repository contains historical and automatically inferred edges.
    # Keep only earlier edges supported by programme evidence or a clear
    # subject-title relationship before ranking and assembly.
    prereq_ids_by_course = filter_supported_prerequisites(
        raw_prereq_ids_by_course,
        courses=courses,
        aggregates=aggregates,
        num_semesters=num_semesters,
        normalize_title=_title_key,
        excluded_prefixes=generic_prerequisite_terms,
    )
    course_depth = make_course_depth(
        prereq_ids_by_course,
        courses=courses,
        num_semesters=num_semesters,
    )
    # A 100-course frontier is sufficient for a one-domain catalogue but can
    # starve a two-direction programme: 40/40 domain quotas may require
    # separate prerequisite chains from both EPVO groups.  Keep the larger
    # bounded frontier only for scoped/professional programmes; it remains
    # deterministic and avoids scanning the full repository.
    candidate_limit = 350 if interdisciplinary or epvo_professional_scope else 100
    candidate_ids = rank_admissible_frontier(
        aggregates,
        is_admissible=lambda cid: is_project_domain(courses[cid]),
        max_depth=num_semesters,
        aggregates=aggregates,
        courses=courses,
        prerequisite_ids_by_course=prereq_ids_by_course,
        course_depth=course_depth,
        role_rank=role_rank,
        scope_rank=scope_rank,
        priority_rank=priority_rank,
        semester_stability_rank=semester_stability_rank,
        variant_type=variant_type,
        project_domains=(version.project.domain1, version.project.domain2),
        title_for=lambda cid: _title_key(courses[cid].title),
        limit=candidate_limit,
    )
    root_credits = sum(
        int(course.credits or 5)
        for course in courses.values()
        if is_project_domain(course) and course_depth(course.id) == 0
    )
    # A one-domain programme must try to fill its complete professional volume
    # with real EPVO courses.  Reserving an artificial first-semester gap here
    # was later filled by several AUTO_BRIDGE modules even when real courses
    # were available.  Only a two-domain design keeps a small explicit reserve
    # for its bounded integration/foundation bridge envelope.
    foundation_reserve = (
        min(
            max(0, int(constraints.get("max_credits_per_semester", 30)) - root_credits),
            bridge_module_limit(version) * 7,
        )
        if interdisciplinary
        else 0
    )
    target = max(0, target - foundation_reserve)
    maximum = target if foundation_reserve else target + max(0, int(constraints.get("credit_tolerance", TOTAL_CREDIT_TOLERANCE)))
    optimizer_cache_key = f"nsga2_variants:{project_version_id}"
    if optimizer_cache_key not in db.info:
        # Interdisciplinary and explicitly EPVO-scoped programmes are handled
        # by the deterministic hard-constraint path below. NSGA-II's early
        # return can satisfy credits before the scoped real-course top-up and
        # therefore replace valid M/B/D-group courses with synthetic bridges.
        # Keep NSGA-II only for unscoped experimental catalogues.
        if interdisciplinary or epvo_professional_scope:
            db.info[optimizer_cache_key] = {}
        else:
            from app.planner.nsga2 import optimize_variants
            domain_catalog_size = sum(1 for course in courses.values() if is_project_domain(course))
            large_catalog = domain_catalog_size >= 1200
            optimizer_seed_ids = candidate_ids[:350] if large_catalog else candidate_ids
            if large_catalog:
                db.info[optimizer_cache_key] = {}
            else:
                db.info[optimizer_cache_key] = optimize_variants(
                    version=version,
                    db=db,
                    seed_course_ids=optimizer_seed_ids,
                    target_credits=target,
                    maximum_credits=maximum,
                    population_size=settings.NSGA2_POPULATION,
                    generations=settings.NSGA2_GENERATIONS,
                    crossover_probability=settings.NSGA2_CROSSOVER_PROBABILITY,
                    mutation_probability=settings.NSGA2_MUTATION_PROBABILITY,
                )
    # Interdisciplinary programmes use the deterministic hard-quota path.
    # The unconstrained NSGA-II seed can violate per-domain minima and should
    # remain an experiment for standard one-domain programmes only.
    optimized = db.info[optimizer_cache_key].get(variant_type)
    if optimized:
        # The optimizer may emit synthetic bridges as part of its seed. Apply
        # the project policy immediately, before any variant-specific repair;
        # an explicit zero budget must never leak a bridge into A/B.
        if int(constraints.get("max_new_courses", 5) or 0) <= 0:
            optimized = [
                dict(item) for item in optimized
                if item.get("bridge_module_id") is None
            ]
        quality_bridge = db.query(BridgeModule).filter(
            BridgeModule.project_version_id == project_version_id,
            BridgeModule.course_id == f"QUALITY_BRIDGE_{project_version_id}",
        ).first()
        if interdisciplinary and quality_bridge and not any(item.get("bridge_module_id") for item in optimized):
            protected_ids = {
                prerequisite_id
                for item in optimized
                for prerequisite_id in (item.get("prerequisites") or [])
            }
            replaceable = [
                (index, item)
                for index, item in enumerate(optimized)
                if item.get("course_id") not in protected_ids
                and int(item.get("credits") or 0) == int(quality_bridge.credits or 0)
            ]
            if replaceable:
                # Keep all variants interdisciplinary while retaining a
                # deterministic distinction between their course sets.
                offset = {"A": 0, "B": 1, "C": 2}.get(variant_type, 0)
                replace_index, _ = replaceable[offset % len(replaceable)]
                optimized = [dict(item) for item in optimized]
                optimized[replace_index] = {
                    "bridge_module_id": quality_bridge.id,
                    "title": quality_bridge.title,
                    "domain": "interdisciplinary",
                    "credits": quality_bridge.credits or 5,
                    "recommended_semester": quality_bridge.recommended_semester,
                    "prerequisites": quality_bridge.prerequisites or [],
                    "type": "bridge",
                }
        for bridge in [core_bridge]:
            optimized = _force_bridge_item(
                optimized, bridge, variant_type, target
            )
        optimized = _promote_epvo_priority_courses(optimized, courses, prereq_ids_by_course, is_project_domain, course_depth, num_semesters, priority_rank, target, maximum)
        optimized = _limit_general_course_items(
            optimized,
            courses,
            project_domains,
            target,
            max_general_percent,
        )
        optimized = _trim_to_target_credits(
            close_professional_lo_gaps(
                top_up_with_credit_bridges(remove_weak_general_items(optimized))
            ),
            target,
            db,
        )
        optimized = _diversify_variant_items(optimized, version, db, variant_type)
        optimized = _trim_to_target_credits(close_professional_lo_gaps(top_up_with_credit_bridges(remove_weak_general_items(optimized))), target, db)
        # The optimized path used to return before the common evidence gate.
        # build_curriculum_plan then removed every real course because the
        # required admission_los/admission_score fields were absent and filled
        # the resulting gap with bridges.  Apply the same final contract as
        # the deterministic path before returning an NSGA-II variant.
        optimized = admit_real_courses(optimized)
        optimized = close_professional_lo_gaps(optimized)
        optimized = admit_real_courses(optimized)
        optimized = top_up_with_credit_bridges(optimized)
        optimized = _trim_to_target_credits(optimized, target, db)
        return _unique_items_by_title(optimized)
    selected: Dict[int, Dict] = {}
    def selected_domain_credit_total(domain_index: int) -> int:
        return selected_domain_credits(
            selected,
            courses=courses,
            domain_index=domain_index,
            domain_share=project_domain_share,
        )

    def bundle(cid: int) -> List[Dict]:
        return build_prerequisite_bundle(
            cid,
            courses=courses,
            prerequisite_ids_by_course=prereq_ids_by_course,
            selected=selected,
            is_project_domain=is_project_domain,
            scope_rank=scope_rank,
        )
    foundation_target = max(0, int(constraints.get("max_credits_per_semester", target / max(num_semesters, 1))) - 3)
    foundation_ids = sorted(
        (cid for cid in courses if is_project_domain(courses[cid]) and course_depth(cid) == 0),
        key=lambda cid: variant_candidate_key(
            cid,
            aggregates=aggregates,
            courses=courses,
            prerequisite_ids_by_course=prereq_ids_by_course,
            course_depth=course_depth,
            role_rank=role_rank,
            scope_rank=scope_rank,
            priority_rank=priority_rank,
            semester_stability_rank=semester_stability_rank,
            variant_type=variant_type,
            project_domains=(version.project.domain1, version.project.domain2),
        ) if cid in aggregates else (0, 0, 0),
        reverse=True,
    )
    total = assemble_foundation_frontier(
        foundation_ids,
        selected=selected,
        bundle_for_course=bundle,
        rank_key=lambda cid: variant_candidate_key(
            cid,
            aggregates=aggregates,
            courses=courses,
            prerequisite_ids_by_course=prereq_ids_by_course,
            course_depth=course_depth,
            role_rank=role_rank,
            scope_rank=scope_rank,
            priority_rank=priority_rank,
            semester_stability_rank=semester_stability_rank,
            variant_type=variant_type,
            project_domains=(version.project.domain1, version.project.domain2),
        ) if cid in aggregates else (0, 0, 0),
        foundation_target=foundation_target,
        maximum_credits=maximum,
    )

    domain_quota_candidate_cache: Dict[int, List[Course]] = {}

    domain_quota_candidates = partial(
        get_domain_quota_candidates,
        cache=domain_quota_candidate_cache,
        courses=courses.values(),
        is_admissible=is_project_domain,
        domain_share=project_domain_share,
        course_depth=course_depth,
        max_depth=num_semesters,
        rank_key=lambda course: (
            -role_rank(course),
            -scope_rank(course),
            -float(aggregates.get(course.id, {}).get("expert") or 0.0),
            -float(aggregates.get(course.id, {}).get("max") or 0.0),
            -len(aggregates.get(course.id, {}).get("professional_lo_codes") or set()),
            -priority_rank(course),
            course.recommended_semester or 99,
            course.id,
        ),
    )

    top_up_with_real_epvo_courses = partial(
        _top_up_with_real_epvo_courses,
        target_credits=target,
        maximum_credits=maximum,
        courses=courses,
        prerequisite_ids_by_course=prereq_ids_by_course,
        aggregates=aggregates,
        num_semesters=num_semesters,
        title_key=_title_key,
        is_project_domain=is_project_domain,
        scope_rank=scope_rank,
        priority_rank=priority_rank,
        course_depth=course_depth,
        course_matches_scope_theme=course_matches_scope_theme,
        has_strong_exact_scope_evidence=has_strong_exact_scope_evidence,
        unique_items_by_title=_unique_items_by_title,
        admit_real_courses=admit_real_courses,
    )

    top_up_real_epvo_callback = top_up_with_real_epvo_courses

    def rebalance_domain_quotas(items: List[Dict]) -> List[Dict]:
        return _rebalance_domain_quotas(
            items,
            interdisciplinary=interdisciplinary,
            constraints=constraints,
            quota_total_credits=quota_total_credits,
            min_domain_percent=min_domain_percent,
            secondary_bridges=secondary_bridges,
            core_bridge=core_bridge,
            db=db,
            courses=courses,
            project_domain_share=project_domain_share,
            project_domain_index=project_domain_index,
            aggregates=aggregates,
            project_domains=project_domains,
            prereq_ids_by_course=prereq_ids_by_course,
            domain_quota_candidates=domain_quota_candidates,
            priority_rank=priority_rank,
            epvo_domain_index=epvo_domain_index,
        )
    # Respect the quotas entered in the project wizard before the generic fill.
    if interdisciplinary:
        total = _reserve_domain_quota(
            1,
            selected=selected,
            total=total,
            maximum=maximum,
            quota_total_credits=quota_total_credits,
            minimum_percentages=min_domain_percent,
            candidate_ids=candidate_ids,
            courses=courses,
            project_domain_share=project_domain_share,
            bundle_for_course=bundle,
            selected_domain_credit_total=selected_domain_credit_total,
        )
    total = _reserve_domain_quota(
        0,
        selected=selected,
        total=total,
        maximum=maximum,
        quota_total_credits=quota_total_credits,
        minimum_percentages=min_domain_percent,
        candidate_ids=candidate_ids,
        courses=courses,
        project_domain_share=project_domain_share,
        bundle_for_course=bundle,
        selected_domain_credit_total=selected_domain_credit_total,
    )

    for cid in candidate_ids:
        total, added = add_bundle_if_fits(selected, bundle(cid), maximum)
        if not added:
            continue
        if total >= target: break
    if total < target:
        fallback_candidates = (
            c for c in courses.values()
            if is_project_domain(c) and course_depth(c.id) < num_semesters
        )
        if variant_type == "C":
            fallback = heapq.nsmallest(
                500,
                fallback_candidates,
                key=lambda c: (-role_rank(c), -scope_rank(c), (c.domain or "").lower(), c.recommended_semester or 99, -c.id),
            )
        else:
            fallback = heapq.nsmallest(
                500,
                fallback_candidates,
                key=lambda c: (-role_rank(c), -scope_rank(c), c.recommended_semester or 99, c.credits or 5, c.id),
            )
        for course in fallback:
            additions = list({item["course_id"]: item for item in bundle(course.id) if item["course_id"] not in selected}.values())
            addition_credits = sum(item["credits"] for item in additions)
            if additions and total + addition_credits <= maximum:
                for item in additions: selected[item["course_id"]] = item
                total = sum(item["credits"] for item in selected.values())
                if total >= target: break
    result = _limit_general_course_items(
        list(selected.values()),
        courses,
        project_domains,
        target,
        max_general_percent,
    )
    result = top_up_with_real_epvo_courses(remove_weak_general_items(result))
    for bridge in [core_bridge]:
        result = _force_bridge_item(result, bridge, variant_type, target)
    result = _trim_to_target_credits(
        close_professional_lo_gaps(top_up_with_credit_bridges(result)),
        target,
        db,
    )
    total = sum(int(item.get("credits") or 0) for item in result)
    if constraints.get("allow_new_courses", True):
        existing_bridge_count = sum(1 for item in result if item.get("bridge_module_id") is not None)
        # Never widen the bridge budget to make a below-target candidate look
        # complete.  The verifier will reject an unresolved real-course gap.
        max_new_courses = bridge_module_limit(version)
        auto_prefix = f"AUTO_BRIDGE_{project_version_id}_"
        expert_bridges = db.query(BridgeModule).filter(
            BridgeModule.project_version_id == project_version_id,
            ~BridgeModule.course_id.like(f"{auto_prefix}%"),
        ).order_by(BridgeModule.id.desc()).all()
        expert_bridges.sort(key=lambda module: (-(module.credits or 5), -module.id))
        seen_bridge_titles = {
            " ".join((item.get("title") or "").lower().split())
            for item in result
            if item.get("bridge_module_id") is not None
        }
        for bm in expert_bridges:
            normalized_title = " ".join((bm.title or "").lower().split())
            if not normalized_title or normalized_title in seen_bridge_titles:
                continue
            credits = bm.credits or 5
            slots_after = max_new_courses - existing_bridge_count - 1
            credits_still_needed = max(0, target - (total + credits))
            # Reserve enough slots for deterministic 7-credit bridge modules;
            # otherwise several small/duplicate AI suggestions can leave the
            # curriculum below its mandatory credit target.
            if credits_still_needed > slots_after * 7:
                continue
            if total + credits <= maximum:
                bridge = _bridge_item(bm)
                bridge["credits"] = credits
                bridge["type"] = "mandatory"
                result.append(bridge)
                total += credits
                existing_bridge_count += 1
                seen_bridge_titles.add(normalized_title)
            if total >= target: break
        remaining_slots = max(0, max_new_courses - existing_bridge_count)
        if total < target and remaining_slots > 0:
            needed = min(maximum - total, target - total)
            desired_count = remaining_slots if variant_type == "C" else None
            auto_modules = ensure_credit_bridge_modules(
                version,
                db,
                needed,
                remaining_slots,
                desired_count=desired_count,
            )
            for bm in auto_modules:
                credits = bm.credits or 5
                if total + credits > maximum:
                    continue
                bridge = _bridge_item(bm)
                bridge["credits"] = credits
                result.append(bridge)
                total += credits
                if total >= target:
                    break
    if variant_type == "B" and not interdisciplinary:
        # Some legacy projects have many equal 5-credit candidates.  In that
        # case the "reuse-first" B heuristic can converge to the same final
        # set as A even when the ordering differs.  Swap a few safe electives
        # for same-credit alternatives from the same project domains so B is a
        # genuine alternative without breaking prerequisites or credits.
        selected_ids = {
            item.get("course_id")
            for item in result
            if item.get("course_id") is not None
        }
        protected_ids = {
            prerequisite_id
            for item in result
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in selected_ids
        }
        alternatives_by_credit: Dict[int, List[Course]] = {}
        for course in courses.values():
            if (
                course.id not in selected_ids
                and is_project_domain(course)
                and course_depth(course.id) < num_semesters
                and not prereq_ids_by_course.get(course.id)
            ):
                alternatives_by_credit.setdefault(int(course.credits or 5), []).append(course)
        for alternatives in alternatives_by_credit.values():
            alternatives.sort(key=lambda course: course.id, reverse=True)
        removable = [
            (index, item)
            for index, item in enumerate(result)
            if item.get("course_id") is not None
            and item.get("course_id") not in protected_ids
        ]
        removable.sort(key=lambda pair: int(pair[1].get("course_id") or 0))
        swaps = 0
        for index, item in removable:
            if swaps >= 4:
                break
            credits = int(item.get("credits") or 5)
            alternative = None
            while alternatives_by_credit.get(credits):
                candidate = alternatives_by_credit[credits].pop(0)
                if candidate.id not in selected_ids:
                    alternative = candidate
                    break
            if alternative is None:
                continue
            selected_ids.discard(item.get("course_id"))
            selected_ids.add(alternative.id)
            result[index] = {
                "course_id": alternative.id,
                "title": alternative.title,
                "domain": alternative.domain,
                "credits": alternative.credits or 5,
                "recommended_semester": alternative.recommended_semester,
                "prerequisites": [],
                "type": alternative.cycle_component or "mandatory",
            }
            swaps += 1
    result = _promote_epvo_priority_courses(result, courses, prereq_ids_by_course, is_project_domain, course_depth, num_semesters, priority_rank, target, maximum)
    if not interdisciplinary:
        result = _limit_general_course_items(
            result,
            courses,
            project_domains,
            target,
            max_general_percent,
        )
    result = rebalance_domain_quotas(result)
    if not (interdisciplinary and variant_type == "B"):
        result = _diversify_variant_items(result, version, db, variant_type)
    result = _trim_to_target_credits(close_professional_lo_gaps(top_up_with_credit_bridges(top_up_with_real_epvo_courses(remove_weak_general_items(result)))), target, db)
    if not interdisciplinary:
        result = _limit_general_course_items(
            result,
            courses,
            project_domains,
            target,
            max_general_percent,
        )
    result = _promote_epvo_priority_courses(
        result,
        courses,
        prereq_ids_by_course,
        lambda course: is_project_domain(course)
        and _course_curriculum_role(course, project_domains) != "general",
        course_depth,
        num_semesters,
        priority_rank,
        target,
        maximum,
    )
    result = _trim_to_target_credits(top_up_with_credit_bridges(top_up_with_real_epvo_courses(result)), target, db)
    result = rebalance_domain_quotas(result)
    replace_redundant_bridge = partial(
        _replace_redundant_bridges,
        db=db,
        courses=courses,
        aggregates=aggregates,
        project_domains=project_domains,
        prerequisite_ids=prereq_ids_by_course,
        is_project_domain=is_project_domain,
        scope_rank=scope_rank,
        course_role=_course_curriculum_role,
        priority_rank=priority_rank,
    )
    result = apply_confirmed_variant_replacements(
        result,
        constraints,
        courses,
        prereq_ids_by_course,
        num_semesters,
        replace_redundant_bridge,
    )
    result = rebalance_domain_quotas(result)
    # Expert replacements are applied late and can change the domain envelope.
    # Recheck quotas once more while keeping those confirmed courses protected.
    result = rebalance_domain_quotas(result)
    # Quota repair and variant diversification may remove the only real source
    # of an LO. Close those gaps again at the true end of selection, then
    # restore quotas once more; bridges never count as real LO evidence here.
    result = close_professional_lo_gaps(result)
    result = rebalance_domain_quotas(result)
    result = close_professional_lo_gaps(result)
    # Run diversification after all priority-promotion passes.  Previously B
    # was diversified earlier and then the final EPVO promotion restored the
    # same courses as A.  Recheck hard quotas and LO gaps after the late swap.
    if variant_type in {"B", "C"}:
        result = _diversify_variant_items(result, version, db, variant_type)
        result = rebalance_domain_quotas(result)
        result = close_professional_lo_gaps(result)
    # Nothing after this point may add an unverified real discipline. Removed
    # credits are filled only by explicit bridge modules, so the UI never
    # presents a catalogue placeholder as an evidence-backed course.
    result = admit_real_courses(result)
    result = top_up_with_credit_bridges(top_up_with_real_epvo_courses(result))
    result = close_professional_lo_gaps(result)
    result = admit_real_courses(result)
    result = top_up_with_credit_bridges(top_up_with_real_epvo_courses(result))
    result = _trim_to_target_credits(result, target, db)
    # The last credit top-up/trim can undo an earlier interdisciplinary quota
    # repair. Keep the final plan envelope honest: no later stage may leave a
    # plan that fails domain quotas if an equal-credit EPVO swap is available.
    result = rebalance_domain_quotas(result)
    result = replace_redundant_bridge(result, protected_bridge_ids=None)
    result = _trim_to_target_credits(result, target, db)
    result = rebalance_domain_quotas(result)
    # The last trim/bridge replacement must not remove the sole real source
    # for a programme LO. Reclose gaps at the true end of selection.
    result = close_professional_lo_gaps(result)
    result = admit_real_courses(result)
    result = top_up_with_real_epvo_courses(result)
    result = top_up_with_credit_bridges(result)
    result = replace_redundant_bridge(result, protected_bridge_ids=None)
    result = _trim_to_target_credits(result, target, db)
    result = _fill_existing_bridge_credit_gap(result, target, db)
    result = rebalance_domain_quotas(result)
    result = _fill_existing_bridge_credit_gap(result, target, db)
    result = top_up_with_credit_bridges(result)
    # The final bridge top-up may increase a flexible module by one credit to
    # close a residual gap.  Enforce the target envelope once more before
    # diversification so every variant is independently admissible (not only
    # the common A schedule).
    result = _trim_to_target_credits(result, target, db)
    # Whole-course trimming cannot resolve a one-credit overage when every
    # remaining real course is protected.  Flex only an existing bridge in
    # that narrow case; its evidence/LO links remain unchanged and the final
    # plan still has an exact target total.
    excess = max(0, sum(int(item.get("credits") or 0) for item in result) - target)
    if excess:
        for item in result:
            if excess <= 0 or item.get("bridge_module_id") is None:
                continue
            current_credits = int(item.get("credits") or 0)
            reduction = min(excess, max(0, current_credits - 1))
            if reduction <= 0:
                continue
            item["credits"] = current_credits - reduction
            module = db.query(BridgeModule).filter(BridgeModule.id == item["bridge_module_id"]).first()
            if module:
                module.credits = item["credits"]
            excess -= reduction
    # Final pass: all credit/domain/LO repairs above can converge B/C back to A.
    # Diversify only after the last mutation so an accepted plan keeps its
    # variant identity. The helper preserves same-credit courses, professional
    # LO coverage, core competencies and prerequisite safety; the verifier
    # remains the final authority for hard constraints.
    if variant_type in {"B", "C"}:
        result = _diversify_variant_items(result, version, db, variant_type)
    if (
        variant_type == "C"
        and str(constraints.get("education_level") or "").lower()
        in {"doctorate", "doctoral", "phd"}
    ):
        preferred_semester = max(1, int(constraints.get("total_semesters") or 6) - 1)
        trajectory_candidates = [
            item for item in result
            if item.get("course_id") is not None
            and not item.get("regulatory_required")
            and int(item.get("credits") or 0) == 5
            and _foundation_max_semester(
                item.get("title"),
                int(constraints.get("total_semesters") or 6),
            ) >= preferred_semester
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
    for item in result:
        course = courses.get(item.get("course_id"))
        domain_index = project_domain_index(course) if course else None
        if domain_index in (0, 1) and project_domains[domain_index]:
            item["domain"] = project_domains[domain_index]
    # Diversification is the final mutating stage.  Normalize once more after
    # it so a replacement cannot reintroduce a one-credit overage.
    result = _unique_items_by_title(result)
    result = _trim_to_target_credits(result, target, db)
    excess = max(0, sum(int(item.get("credits") or 0) for item in result) - target)
    if excess:
        for item in result:
            if excess <= 0 or item.get("bridge_module_id") is None:
                continue
            current_credits = int(item.get("credits") or 0)
            reduction = min(excess, max(0, current_credits - 1))
            if reduction <= 0:
                continue
            item["credits"] = current_credits - reduction
            module = db.query(BridgeModule).filter(BridgeModule.id == item["bridge_module_id"]).first()
            if module:
                module.credits = item["credits"]
            excess -= reduction
    return result
