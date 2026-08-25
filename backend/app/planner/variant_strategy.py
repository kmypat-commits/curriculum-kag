from __future__ import annotations

from functools import partial
from itertools import combinations
import math
import re
from statistics import median
from typing import Dict, List

from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.bridge_module import BridgeModule
from app.models.course import Course, course_prerequisites
from app.models.embedding import MatchScore
from app.models.epvo import (
    EpvoDirection,
    EpvoDisciplineLoLink,
    EpvoDisciplineNormalized,
    EpvoGroup,
)
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
from app.planner.domain_evidence import domain_credit_shares, domain_label_matches
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
from app.services.epvo_repository import (
    epvo_row_matches_education_level,
    epvo_row_relevance_score,
)

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
from app.planner.variant_assembly import add_bundle_if_fits, build_prerequisite_bundle
from app.planner.variant_admission import is_project_domain_course as _is_project_domain_course
from app.planner.variant_ranking import rank_variant_candidates, variant_candidate_key
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

    def remove_weak_general_items(items: List[Dict]) -> List[Dict]:
        if not professional_scope:
            return items
        cleaned = []
        for item in items:
            course = courses.get(item.get("course_id"))
            if course and _course_curriculum_role(course, project_domains) == "general":
                evidence = aggregates.get(course.id, {})
                if float(evidence.get("max") or 0.0) < min_general_lo_evidence:
                    continue
            cleaned.append(item)
        return cleaned

    def top_up_with_credit_bridges(items: List[Dict]) -> List[Dict]:
        if not constraints.get("allow_new_courses", True):
            return items
        # This helper is called again after quota, duplicate and prerequisite
        # repairs.  Those repairs can remove a real course and reopen an exact
        # credit gap.  Retry the real EPVO fill at that final point before a
        # synthetic bridge is even considered.
        items = top_up_with_real_epvo_courses(items)
        total_now = sum(int(item.get("credits") or 0) for item in items)
        if total_now >= target:
            return items
        current_bridge_count = sum(1 for item in items if item.get("bridge_module_id") is not None)
        remaining_slots = max(0, int(constraints.get("max_new_courses", 5)) - current_bridge_count)
        # A late duplicate/prerequisite cleanup can leave a small exact-credit
        # gap after all configured bridge slots are occupied. One explicit
        # 3-credit bridge is safer than persisting an invalid below-target plan;
        # it is recorded as a credit-repair event in the plan metadata.
        if remaining_slots <= 0 and 0 < target - total_now <= 3:
            remaining_slots = 1
        if remaining_slots <= 0:
            return items
        auto_modules = ensure_credit_bridge_modules(
            version,
            db,
            min(maximum - total_now, target - total_now),
            remaining_slots,
            desired_count=remaining_slots if variant_type == "C" else None,
        )
        normalized = list(items)
        for bm in auto_modules:
            credits = int(bm.credits or 5)
            if total_now + credits > maximum:
                continue
            bridge = _bridge_item(bm)
            bridge["credits"] = credits
            normalized.append(bridge)
            total_now += credits
            if total_now >= target:
                break
        return normalized

    def close_professional_lo_gaps(items: List[Dict]) -> List[Dict]:
        if not professional_scope:
            return items
        normalized = [dict(item) for item in items]
        lo_by_id = {
            lo.id: lo
            for lo in version.learning_outcomes
            if not str(lo.lo_code or "").startswith("LO-GOSO-")
        }
        if not lo_by_id:
            return normalized
        selected_course_ids = [int(item["course_id"]) for item in normalized if item.get("course_id")]
        score_by_course: Dict[int, Dict[str, float]] = {}
        expert_by_course: Dict[int, Dict[str, float]] = {}
        for match in db.query(MatchScore).filter(
            MatchScore.project_version_id == project_version_id,
            MatchScore.lo_id.in_(list(lo_by_id)),
        ).all():
            lo = lo_by_id.get(match.lo_id)
            if not lo:
                continue
            expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
            effective = max(float(match.score or 0.0), expert)
            score_by_course.setdefault(int(match.course_id), {})[lo.lo_code] = max(
                score_by_course.get(int(match.course_id), {}).get(lo.lo_code, 0.0),
                effective,
            )
            expert_by_course.setdefault(int(match.course_id), {})[lo.lo_code] = max(
                expert_by_course.get(int(match.course_id), {}).get(lo.lo_code, 0.0),
                expert,
            )
        # A proposed bridge is not evidence that a real discipline covers the
        # outcome.  Real-course gaps remain open until an EPVO/confirmed course
        # reaches the threshold; bridges are reported separately by verifier.
        # Use the same threshold as the verifier.  The old 0.50 repair
        # threshold could leave an LO at 0.55 while the final quality gate
        # correctly required 0.60, producing a plan that the generator itself
        # immediately marked as incomplete.
        required_coverage = float(settings.COVERAGE_THRESHOLD)

        def coverage_state(values: List[Dict]) -> tuple[Dict[str, float], Dict[str, float], List[str]]:
            products = {lo.lo_code: 1.0 for lo in lo_by_id.values()}
            maximums = {lo.lo_code: 0.0 for lo in lo_by_id.values()}
            for item in values:
                course_id = int(item.get("course_id") or 0)
                for code, score in score_by_course.get(course_id, {}).items():
                    bounded = max(0.0, min(1.0, float(score)))
                    products[code] *= 1.0 - bounded
                    maximums[code] = max(maximums[code], bounded)
            coverage = {code: 1.0 - product for code, product in products.items()}
            missing_codes = [
                code
                for code in coverage
                if coverage[code] + 1e-9 < required_coverage
                or maximums[code] + 1e-9 < 0.5
            ]
            return coverage, maximums, missing_codes

        def coverage_objective(values: List[Dict]) -> tuple:
            coverage, maximums, missing_codes = coverage_state(values)
            return (
                len(coverage) - len(missing_codes),
                min(coverage.values(), default=0.0),
                sum(coverage.values()),
                sum(maximums.values()),
            )

        coverage, maximums, missing = coverage_state(normalized)
        if not missing:
            return normalized

        # Repair LO gaps with real, in-scope EPVO disciplines first.  A bridge
        # is only a last resort when the repository has no sufficiently strong
        # course with the same credit volume.  Expert EPVO evidence is part of
        # the rank, not merely a UI annotation.
        selected_ids = {item.get("course_id") for item in normalized if item.get("course_id") is not None}
        protected_ids = {
            prerequisite
            for item in normalized
            for prerequisite in (item.get("prerequisites") or [])
            if prerequisite in selected_ids
        }
        missing_lo_ids = {lo.id for lo in lo_by_id.values() if lo.lo_code in missing}
        candidate_evidence: Dict[int, Dict] = {}
        if missing_lo_ids:
            for match in db.query(MatchScore).filter(
                MatchScore.project_version_id == project_version_id,
                MatchScore.lo_id.in_(missing_lo_ids),
                MatchScore.score >= 0.3,
            ).all():
                course = courses.get(int(match.course_id))
                if (
                    not course
                    or course.id in selected_ids
                    or not str(course.course_id or "").startswith("EPVO-")
                    or scope_rank(course) <= 0
                    or not is_project_domain(course)
                ):
                    continue
                lo = lo_by_id.get(match.lo_id)
                if not lo:
                    continue
                evidence = candidate_evidence.setdefault(course.id, {
                    "los": set(), "max": 0.0, "expert": 0.0, "scores": {},
                })
                expert_value = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
                effective_score = max(float(match.score or 0.0), expert_value)
                if effective_score < 0.4:
                    continue
                evidence["los"].add(lo.lo_code)
                evidence["max"] = max(evidence["max"], effective_score)
                evidence["scores"][lo.lo_code] = max(
                    evidence["scores"].get(lo.lo_code, 0.0),
                    effective_score,
                )
                evidence["expert"] = max(
                    evidence["expert"],
                    expert_value,
                )

        real_candidates = sorted(
            (courses[cid] for cid in candidate_evidence),
            key=lambda course: (
                len(candidate_evidence[course.id]["los"]),
                candidate_evidence[course.id]["expert"] > 0,
                candidate_evidence[course.id]["expert"],
                candidate_evidence[course.id]["max"],
                scope_rank(course),
                priority_rank(course),
            ),
            reverse=True,
        )
        for candidate in real_candidates:
            evidence = candidate_evidence[candidate.id]
            still_missing = set(missing) & set(evidence["los"])
            if not still_missing:
                continue
            candidate_credits = int(candidate.credits or 5)
            candidate_item = {
                "course_id": candidate.id,
                "title": candidate.title,
                "domain": candidate.domain,
                "credits": candidate_credits,
                "recommended_semester": candidate.recommended_semester,
                "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                "type": candidate.cycle_component or "mandatory",
                "selection_method": "epvo_lo_gap_repair",
                "selection_evidence": {
                    "target_los": sorted(still_missing),
                    "model_score": round(float(evidence["max"]), 4),
                    "epvo_expert_score": round(float(evidence["expert"]), 4),
                },
            }
            current_objective = coverage_objective(normalized)
            best_trial = None
            best_objective = current_objective
            for index, item in enumerate(normalized):
                if (
                    item.get("bridge_module_id") is not None
                    and int(item.get("credits") or 0) == candidate_credits
                ):
                    pass
                else:
                    old_course = courses.get(item.get("course_id"))
                    if (
                        not old_course
                        or old_course.id in protected_ids
                        or item.get("regulatory_required")
                        or int(item.get("credits") or 0) != candidate_credits
                    ):
                        continue
                trial = [dict(value) for value in normalized]
                trial[index] = dict(candidate_item)
                objective = coverage_objective(trial)
                if objective > best_objective:
                    best_objective = objective
                    best_trial = trial
            if best_trial is None:
                continue
            normalized = best_trial
            selected_ids.add(candidate.id)
            coverage, maximums, missing = coverage_state(normalized)
            if not missing:
                return _unique_items_by_title(normalized)

        if not constraints.get("allow_new_courses", True):
            return _unique_items_by_title(normalized)
        current_bridge_count = sum(1 for item in normalized if item.get("bridge_module_id") is not None)
        slots = max(0, int(constraints.get("max_new_courses", 5)) - current_bridge_count)
        if slots <= 0:
            return normalized
        selected_ids = {item.get("course_id") for item in normalized if item.get("course_id") is not None}
        protected_ids = {
            prerequisite
            for item in normalized
            for prerequisite in (item.get("prerequisites") or [])
            if prerequisite in selected_ids
        }
        replaceable = []
        for index, item in enumerate(normalized):
            course = courses.get(item.get("course_id"))
            if not course or course.id in protected_ids:
                continue
            evidence = aggregates.get(course.id, {})
            replaceable.append((
                _course_role_rank(course, project_domains),
                priority_rank(course),
                float(evidence.get("max") or 0.0),
                int(course.credits or item.get("credits") or 5),
                index,
                item,
            ))
        replaceable.sort(key=lambda row: (row[0], row[1], row[2], -row[3]))
        module_count = min(slots, len(missing), len(replaceable))
        if module_count <= 0:
            return normalized
        total_semesters = int(constraints.get("total_semesters", 8) or 8)
        chunks = [missing[index::module_count] or missing for index in range(module_count)]
        support_by_course: Dict[int, List[str]] = {}
        if selected_course_ids:
            for match in db.query(MatchScore).filter(
                MatchScore.project_version_id == project_version_id,
                MatchScore.course_id.in_(selected_course_ids),
                MatchScore.score >= 0.4,
            ).all():
                lo = lo_by_id.get(match.lo_id)
                if lo:
                    support_by_course.setdefault(int(match.course_id), []).append(lo.lo_code)
        replacement_indexes = []
        modules = []
        for index in range(module_count):
            _role, _priority, _score, credits, item_index, old_item = replaceable[index]
            credits = max(3, int(credits or 3))
            codes = list(dict.fromkeys([
                *chunks[index],
                *support_by_course.get(int(old_item.get("course_id") or 0), []),
            ]))
            code = f"LO_GAP_BRIDGE_{project_version_id}_{variant_type}_{index + 1}"
            title = f"Модуль закрытия пробелов результатов обучения {', '.join(codes)}"
            module = db.query(BridgeModule).filter(
                BridgeModule.project_version_id == project_version_id,
                BridgeModule.course_id == code,
            ).first()
            payload = {
                "title": title,
                "goal": f"Закрыть недостаточно подтверждённые результаты обучения: {', '.join(codes)}.",
                "description": (
                    "Автоматически созданный bridge-модуль заменяет слабую дисциплину, "
                    "когда текущий учебный план не подтверждает один или несколько результатов обучения."
                ),
                "credits": credits,
                "recommended_semester": max(2, min(total_semesters - 1, 3 + index)),
                "learning_outcomes": [
                    f"Демонстрировать достижение результатов обучения {', '.join(codes)} на практическом кейсе.",
                    "Связывать теоретические знания, инструменты и доказательства с требованиями образовательной программы.",
                ],
                "topics": [
                    "Диагностика пробела результата обучения",
                    "Практический кейс и доказательства достижения",
                    "Инструменты, методы и ограничения",
                    "Портфолио результата обучения",
                ],
                "assessment_methods": ["практический кейс", "портфолио", "защита проекта"],
                "target_los": codes,
            }
            if module is None:
                module = BridgeModule(
                    project_version_id=project_version_id,
                    course_id=code,
                    prerequisites=[],
                    source_chunks_json=[],
                    generation_params_json={"mode": "professional_lo_gap_bridge", "variant": variant_type},
                    **payload,
                )
                db.add(module)
            else:
                for key, value in payload.items():
                    setattr(module, key, value)
                module.prerequisites = []
                module.generation_params_json = {"mode": "professional_lo_gap_bridge", "variant": variant_type}
            modules.append(module)
            replacement_indexes.append(item_index)
        db.flush()
        for item_index, module in zip(replacement_indexes, modules):
            normalized[item_index] = _bridge_item(module)
            normalized[item_index]["selection_method"] = "professional_lo_gap_bridge"
        return _unique_items_by_title(normalized)

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
    group_codes = [
        str(value or "").strip()
        for value in (constraints.get("group_code"), constraints.get("secondary_group_code"))
        if str(value or "").strip()
    ]
    direction_codes = [
        str(value or "").strip()
        for value in (constraints.get("direction_code"), constraints.get("secondary_direction_code"))
        if str(value or "").strip()
    ]
    primary_group = str(constraints.get("group_code") or "").strip()
    secondary_group = str(constraints.get("secondary_group_code") or "").strip()
    primary_direction = str(constraints.get("direction_code") or "").strip()
    secondary_direction = str(constraints.get("secondary_direction_code") or "").strip()
    epvo_scope = {}
    epvo_priority = {}
    epvo_scope_by_id: Dict[int, int] = {}
    epvo_priority_by_id: Dict[int, int] = {}
    epvo_domain_evidence: Dict[int, List[int]] = {}
    epvo_semester_values: Dict[int, List[int]] = {}
    if group_codes or direction_codes:
        scope_conditions = [
            cast(EpvoDisciplineNormalized.group_codes, String).like(f'%"{code}"%')
            for code in group_codes
        ] + [
            cast(EpvoDisciplineNormalized.direction_codes, String).like(f'%"{code}"%')
            for code in direction_codes
        ]
        matched_rows = db.query(EpvoDisciplineNormalized).filter(
            EpvoDisciplineNormalized.approved_course_id.isnot(None),
            EpvoDisciplineNormalized.approved_course_id.in_(list(aggregates) or [-1]),
            or_(*scope_conditions),
        ).all()
        for row in matched_rows:
            row_groups = row.group_codes or []
            row_directions = row.direction_codes or []
            rank_value = (
                3 if any(code in row_groups for code in group_codes)
                else 2 if any(code in row_directions for code in direction_codes)
                else 0
            )
            if rank_value <= 0:
                continue
            source_count = len(row.source_programs or [])
            relevance_value = epvo_row_relevance_score(row, version)
            programme_evidence = aggregates.get(int(row.approved_course_id), {})
            strong_program_evidence = (
                float(programme_evidence.get("max") or 0.0) >= float(settings.COVERAGE_THRESHOLD)
                or float(programme_evidence.get("expert") or 0.0) >= 0.5
            )
            # Exact membership in the selected EPVO group already proves the
            # catalogue scope and education level.  The lightweight row-title
            # relevance heuristic is only a guard for the broader direction
            # fallback; it must not discard a D094/M094/B057 discipline that
            # has a strong project-specific discipline--LO score.
            if relevance_value < 0.52 and rank_value < 3 and not strong_program_evidence:
                continue
            epvo_level_scope_allowed_ids.add(int(row.approved_course_id))
            typical_semester = int(row.typical_semester or 0)
            if 1 <= typical_semester <= int(constraints.get("total_semesters") or 8):
                epvo_semester_values.setdefault(int(row.approved_course_id), []).append(typical_semester)
            # Project-specific expert evidence is already present in
            # MatchScore. Avoid aggregating the entire multi-million-link EPVO
            # table for every A/B/C variant merely as a tie-breaker.
            priority_value = int(relevance_value * 1000) + rank_value * 100 + min(source_count, 50) * 5
            primary_scope = (
                3 if primary_group and primary_group in row_groups
                else 2 if primary_direction and primary_direction in row_directions
                else 0
            )
            secondary_scope = (
                3 if secondary_group and secondary_group in row_groups
                else 2 if secondary_direction and secondary_direction in row_directions
                else 0
            )
            mapped_course = courses.get(row.approved_course_id)
            if mapped_course:
                epvo_scope_by_id[mapped_course.id] = max(
                    epvo_scope_by_id.get(mapped_course.id, 0), rank_value,
                )
                epvo_priority_by_id[mapped_course.id] = max(
                    epvo_priority_by_id.get(mapped_course.id, 0), priority_value,
                )
                evidence = epvo_domain_evidence.setdefault(mapped_course.id, [0, 0])
                evidence[0] = max(evidence[0], primary_scope)
                evidence[1] = max(evidence[1], secondary_scope)
            for title in (row.title_ru, row.title_kk, row.title_en):
                if title:
                    key = _title_key(title)
                    epvo_scope[key] = max(epvo_scope.get(key, 0), rank_value)
                    epvo_priority[key] = max(epvo_priority.get(key, 0), priority_value)
        for course_id, (primary_score, secondary_score) in epvo_domain_evidence.items():
            if primary_score or secondary_score:
                epvo_domain_shares[course_id] = domain_credit_shares(
                    primary_score, secondary_score
                )
                epvo_domain_index[course_id] = 1 if secondary_score > primary_score else 0

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

    def prerequisite_title_stems(course: Course) -> set[str]:
        return {
            token[:7]
            for token in re.findall(r"[\w]+", _title_key(course.title), flags=re.UNICODE)
            if len(token) >= 5 and not any(token.startswith(value) for value in generic_prerequisite_terms)
        }

    # The repository contains historical and automatically inferred edges.
    # For generation, retain only an earlier prerequisite that is supported by
    # this programme's LO evidence or by a clear subject-title relationship.
    filtered_prerequisites: Dict[int, List[int]] = {}
    for course_id, prerequisite_ids in raw_prereq_ids_by_course.items():
        course = courses.get(course_id)
        if not course:
            continue
        course_stems = prerequisite_title_stems(course)
        for prerequisite_id in prerequisite_ids:
            prerequisite = courses.get(prerequisite_id)
            if not prerequisite:
                continue
            if int(prerequisite.recommended_semester or 1) >= int(course.recommended_semester or 1):
                continue
            evidence_score = float(aggregates.get(prerequisite_id, {}).get("max") or 0.0)
            shared_stems = course_stems & prerequisite_title_stems(prerequisite)
            if evidence_score < 0.25 and len(shared_stems) < 2:
                continue
            filtered_prerequisites.setdefault(course_id, []).append(prerequisite_id)
    prereq_ids_by_course = filtered_prerequisites

    num_semesters = int(constraints.get("total_semesters", 8))
    depth_cache = {}
    def course_depth(cid, path=None):
        if cid in depth_cache: return depth_cache[cid]
        path = path or set()
        if cid in path or cid not in courses: return num_semesters + 1
        prereqs = prereq_ids_by_course.get(cid, [])
        value = 0 if not prereqs else 1 + max(course_depth(pre_id, path | {cid}) for pre_id in prereqs)
        depth_cache[cid] = value
        return value
    # A 100-course frontier is sufficient for a one-domain catalogue but can
    # starve a two-direction programme: 40/40 domain quotas may require
    # separate prerequisite chains from both EPVO groups.  Keep the larger
    # bounded frontier only for scoped/professional programmes; it remains
    # deterministic and avoids scanning the full repository.
    candidate_limit = 350 if interdisciplinary or epvo_professional_scope else 100
    candidate_ids = rank_variant_candidates(
        (cid for cid in aggregates if cid in courses and is_project_domain(courses[cid]) and course_depth(cid) < num_semesters),
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
    def bundle(cid: int) -> List[Dict]:
        return build_prerequisite_bundle(
            cid,
            courses=courses,
            prerequisite_ids_by_course=prereq_ids_by_course,
            selected=selected,
            is_project_domain=is_project_domain,
            scope_rank=scope_rank,
        )
    total = 0
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
    for cid in foundation_ids:
        foundation_bundle = bundle(cid)
        item = foundation_bundle[-1] if foundation_bundle else None
        if not item or total + item["credits"] > maximum: continue
        selected[cid] = item; total += item["credits"]
        if total >= foundation_target: break

    def selected_domain_credits(domain_index: int) -> int:
        value = 0.0
        for item in selected.values():
            course = courses.get(item.get("course_id"))
            if course:
                value += int(item.get("credits") or 0) * project_domain_share(
                    course, domain_index
                )
        return int(round(value))

    domain_quota_candidate_cache: Dict[int, List[Course]] = {}

    def domain_quota_candidates(domain_index: int) -> List[Course]:
        cached = domain_quota_candidate_cache.get(domain_index)
        if cached is not None:
            return cached
        cached = sorted(
            (
                course for course in courses.values()
                if is_project_domain(course)
                and project_domain_share(course, domain_index) > 0.0
                and course_depth(course.id) < num_semesters
            ),
            key=lambda course: (
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
        domain_quota_candidate_cache[domain_index] = cached
        return cached

    def top_up_with_real_epvo_courses(items: List[Dict]) -> List[Dict]:
        """Prefer real scoped EPVO courses before synthetic credit bridges."""
        normalized = _unique_items_by_title(admit_real_courses(items))
        total_now = sum(int(item.get("credits") or 0) for item in normalized)
        if total_now >= target:
            return normalized
        selected_ids = {int(item.get("course_id")) for item in normalized if item.get("course_id")}
        selected_titles = {_title_key(item.get("title")) for item in normalized if item.get("title")}
        candidates = []
        for course in courses.values():
            if course.id in selected_ids or _title_key(course.title) in selected_titles:
                continue
            if not str(course.course_id or "").startswith("EPVO-"):
                continue
            if not is_project_domain(course) or scope_rank(course) <= 0:
                continue
            if not course_matches_scope_theme(course) and not has_strong_exact_scope_evidence(course):
                continue
            if course_depth(course.id) >= num_semesters:
                continue
            prerequisites = prereq_ids_by_course.get(course.id, [])
            if any(pre_id not in selected_ids for pre_id in prerequisites):
                continue
            evidence = aggregates.get(course.id, {})
            if not evidence.get("professional_lo_codes"):
                continue
            candidates.append(course)
        candidates.sort(key=lambda course: (
            -scope_rank(course),
            -priority_rank(course),
            -float(aggregates.get(course.id, {}).get("max") or 0.0),
            course.recommended_semester or 99,
            course.id,
        ))
        for course in candidates:
            credits = int(course.credits or 5)
            if total_now + credits > maximum:
                continue
            normalized.append({
                "course_id": course.id,
                "title": course.title,
                "domain": course.domain,
                "credits": credits,
                "recommended_semester": course.recommended_semester,
                "prerequisites": prereq_ids_by_course.get(course.id, []),
                "type": course.cycle_component or "elective",
                "epvo_exact_scope": scope_rank(course) >= 3,
                "selection_method": "real_epvo_credit_top_up",
            })
            selected_ids.add(course.id)
            selected_titles.add(_title_key(course.title))
            total_now += credits
            if total_now >= target:
                break
        return admit_real_courses(normalized)

    def rebalance_domain_quotas(items: List[Dict]) -> List[Dict]:
        if not interdisciplinary:
            return items
        domain_quota_tolerance = max(
            0.0, float(constraints.get("domain_quota_tolerance_credits", 3) or 0)
        )
        required = [
            max(
                0.0,
                math.ceil(
                    max(
                        0,
                        int(constraints.get("total_credits", quota_total_credits) or quota_total_credits)
                        - sum(
                            int(item.get("credits") or 0)
                            for item in items
                            if item.get("regulatory_required")
                        ),
                    )
                    * min_domain_percent[index]
                    / 100
                )
                - domain_quota_tolerance,
            )
            for index in range(2)
        ]
        if not any(required):
            return items
        normalized = [dict(item) for item in items]

        secondary_bridge_ids = {bridge.id for bridge in secondary_bridges}
        core_bridge_id = core_bridge.id if core_bridge is not None else None
        domain_bridge_codes = {
            bridge.id: str(bridge.course_id or "")
            for bridge in [*(secondary_bridges or []), *([core_bridge] if core_bridge is not None else [])]
        }
        bridge_ids_in_plan = {
            int(item.get("bridge_module_id"))
            for item in normalized
            if item.get("bridge_module_id") is not None
        }
        if bridge_ids_in_plan:
            domain_bridge_codes.update({
                bridge.id: str(bridge.course_id or "")
                for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids_in_plan)).all()
            })

        def credits_by_domain() -> List[float]:
            values = [0.0, 0.0]
            for item in normalized:
                course = courses.get(item.get("course_id"))
                if course is not None:
                    credits = float(item.get("credits") or 0)
                    shares = [
                        project_domain_share(course, index)
                        for index in range(2)
                    ]
                    if any(shares):
                        values[0] += credits * shares[0]
                        values[1] += credits * shares[1]
                        continue
                index = project_domain_index(course) if course else None
                if index in (0, 1):
                    values[index] += float(item.get("credits") or 0)
                    continue
                bridge_id = item.get("bridge_module_id")
                credits = float(item.get("credits") or 0)
                if bridge_id in secondary_bridge_ids:
                    values[1] += credits
                elif bridge_id == core_bridge_id or str(domain_bridge_codes.get(bridge_id) or "").startswith(("AUTO_BRIDGE_", "QUALITY_BRIDGE_")):
                    values[0] += credits / 2.0
                    values[1] += credits / 2.0
            return values

        def selected_ids() -> set:
            return {item.get("course_id") for item in normalized if item.get("course_id") is not None}

        baseline_course_ids = selected_ids()
        baseline_courses = [courses[course_id] for course_id in baseline_course_ids if course_id in courses]
        baseline_core_ids = {
            int(course.id)
            for course in baseline_courses
            if _course_curriculum_role(course, project_domains) == "core"
        }
        baseline_professional_codes = {
            str(code)
            for course_id in baseline_course_ids
            for code in (aggregates.get(course_id, {}).get("professional_lo_codes") or set())
        }
        baseline_lo_scores = {}
        for course_id in baseline_course_ids:
            for lo_code, score in (aggregates.get(course_id, {}).get("lo_scores") or {}).items():
                baseline_lo_scores[str(lo_code)] = max(
                    float(baseline_lo_scores.get(str(lo_code)) or 0.0), float(score or 0.0)
                )

        def quality_preserved(trial_items: List[Dict]) -> bool:
            """Reject quota swaps that improve percentages by breaking quality."""
            trial_ids = {
                item.get("course_id") for item in trial_items
                if item.get("course_id") is not None
            }
            if not baseline_core_ids.issubset(trial_ids):
                return False
            trial_codes = {
                str(code)
                for course_id in trial_ids
                for code in (aggregates.get(course_id, {}).get("professional_lo_codes") or set())
            }
            if not baseline_professional_codes.issubset(trial_codes):
                return False
            trial_lo_scores = {}
            for course_id in trial_ids:
                for lo_code, score in (aggregates.get(course_id, {}).get("lo_scores") or {}).items():
                    trial_lo_scores[str(lo_code)] = max(
                        float(trial_lo_scores.get(str(lo_code)) or 0.0), float(score or 0.0)
                    )
            return all(
                float(trial_lo_scores.get(lo_code) or 0.0) + 1e-9 >= score
                for lo_code, score in baseline_lo_scores.items()
            )

        def protected_ids() -> set:
            ids = selected_ids()
            prerequisite_ids = {
                prerequisite_id
                for item in normalized
                for prerequisite_id in (item.get("prerequisites") or [])
                if prerequisite_id in ids
            }
            expert_confirmed_ids = {
                int(course_id)
                for mapping_name in ("confirmed_bridge_replacements", "confirmed_course_replacements")
                for course_id in (constraints.get(mapping_name) or {}).values()
                if str(course_id).isdigit()
            }
            quota_reserve_ids = {
                int(item["course_id"])
                for item in normalized
                if item.get("course_id") is not None
                and item.get("domain_quota_reserve")
            }
            competency_ids = {
                int(item["course_id"])
                for item in normalized
                if item.get("course_id") is not None
                and item.get("competency_required")
            }
            # Quota repair must never remove the only professional LO source
            # or a core competency block. Such a swap can make the numeric
            # domain percentage look better while silently producing an
            # invalid curriculum.
            core_ids = {
                int(item["course_id"])
                for item in normalized
                if item.get("course_id") is not None
                and courses.get(item.get("course_id")) is not None
                and _course_curriculum_role(courses[item["course_id"]], project_domains) == "core"
            }
            lo_sources: Dict[str, set[int]] = {}
            for item in normalized:
                course_id = item.get("course_id")
                evidence = aggregates.get(course_id, {})
                for lo_code in evidence.get("professional_lo_codes") or set():
                    lo_sources.setdefault(str(lo_code), set()).add(int(course_id))
            unique_lo_ids = {
                course_id
                for source_ids in lo_sources.values()
                if len(source_ids) == 1
                for course_id in source_ids
            }
            return (
                prerequisite_ids
                | expert_confirmed_ids
                | quota_reserve_ids
                | competency_ids
                | core_ids
                | unique_lo_ids
            )

        for domain_index in (0, 1):
            guard = 0
            # A 40% quota may require more than twenty 3-credit swaps. Stop
            # only after the plan-sized safety limit or when no valid swap is
            # available, not at an arbitrary fixed count.
            guard_limit = max(20, len(normalized) * 2)
            while credits_by_domain()[domain_index] < required[domain_index] and guard < guard_limit:
                guard += 1
                current = credits_by_domain()
                ids = selected_ids()
                titles = {_title_key(item.get("title")) for item in normalized if item.get("title")}
                candidates = [
                    course for course in domain_quota_candidates(domain_index)
                    if course.id not in ids
                    and _title_key(course.title) not in titles
                    and all(pre_id in ids for pre_id in prereq_ids_by_course.get(course.id, []))
                ][:80]
                swapped = False
                protected = protected_ids()
                for candidate in candidates:
                    candidate_credits = int(candidate.credits or 5)
                    replaceable = []
                    for index, item in enumerate(normalized):
                        course = courses.get(item.get("course_id"))
                        replace_domain = project_domain_index(course) if course else None
                        can_reduce_replace_domain = (
                            replace_domain not in (0, 1)
                            or current[replace_domain] - candidate_credits >= required[replace_domain]
                        )
                        if (
                            course
                            and not item.get("regulatory_required")
                            and item.get("course_id") not in protected
                            and replace_domain != domain_index
                            and int(item.get("credits") or 0) == candidate_credits
                            and can_reduce_replace_domain
                        ):
                            replaceable.append((index, item, course))
                    if not replaceable:
                        continue
                    replaceable.sort(
                        key=lambda row: (
                            _course_role_rank(row[2], project_domains),
                            priority_rank(row[2]),
                            int(row[1].get("recommended_semester") or 99),
                        )
                    )
                    replace_index, _old_item, _old_course = replaceable[0]
                    replacement_item = {
                        "course_id": candidate.id,
                        "title": candidate.title,
                        "domain": candidate.domain,
                        "credits": candidate.credits or 5,
                        "recommended_semester": candidate.recommended_semester,
                        "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                        "type": candidate.cycle_component or "mandatory",
                        "selection_method": "domain_quota_rebalance",
                    }
                    trial = [
                        replacement_item if index == replace_index else item
                        for index, item in enumerate(normalized)
                    ]
                    if not quality_preserved(trial):
                        continue
                    normalized[replace_index] = replacement_item
                    swapped = True
                    break
                if not swapped:
                    # Credit values in EPVO are heterogeneous (3/4/5). A
                    # strict one-for-one swap can stop below quota even when
                    # enough strong courses exist. Try a bounded 1–3 course
                    # exchanges with exactly the same total credits.
                    replaceable_all = []
                    for index, item in enumerate(normalized):
                        course = courses.get(item.get("course_id"))
                        replace_domain = project_domain_index(course) if course else None
                        if (
                            course
                            and not item.get("regulatory_required")
                            and item.get("course_id") not in protected
                            and replace_domain != domain_index
                        ):
                            replaceable_all.append((index, item, course))
                    replacement_groups: Dict[int, List[tuple]] = {}
                    for size in (1, 2, 3):
                        for group in combinations(replaceable_all, size):
                            group_credits = sum(int(row[1].get("credits") or 0) for row in group)
                            removed = [
                                sum(
                                    int(row[1].get("credits") or 0)
                                    * project_domain_share(row[2], index)
                                    for row in group
                                )
                                for index in range(2)
                            ]
                            if all(
                                current[index] - removed[index] >= required[index]
                                for index in range(2)
                                if index != domain_index
                            ):
                                replacement_groups.setdefault(group_credits, []).append(group)
                    candidate_groups = [*( (course,) for course in candidates )]
                    # Keep the exact exchange search bounded. The candidate
                    # list is already ranked by LO/expert/scope evidence; a
                    # 16-item frontier captures the high-quality options
                    # without turning a large EPVO programme into an O(n^4)
                    # planner step.
                    bounded_candidates = candidates[:16]
                    candidate_groups.extend(combinations(bounded_candidates, 2))
                    candidate_groups.extend(combinations(bounded_candidates, 3))
                    for candidate_group in candidate_groups:
                        group_credits = sum(int(course.credits or 5) for course in candidate_group)
                        replacements = replacement_groups.get(group_credits)
                        if not replacements:
                            continue
                        replacement_group = min(
                            replacements,
                            key=lambda group: sum(
                                _course_role_rank(row[2], project_domains) * 1000
                                + priority_rank(row[2])
                                for row in group
                            ),
                        )
                        replacement_indexes = {row[0] for row in replacement_group}
                        trial = [
                            item for index, item in enumerate(normalized)
                            if index not in replacement_indexes
                        ] + [
                            {
                                "course_id": candidate.id,
                                "title": candidate.title,
                                "domain": candidate.domain,
                                "credits": candidate.credits or 5,
                                "recommended_semester": candidate.recommended_semester,
                                "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                                "type": candidate.cycle_component or "mandatory",
                                "selection_method": "domain_quota_group_rebalance",
                            }
                            for candidate in candidate_group
                        ]
                        if not quality_preserved(trial):
                            continue
                        for replace_index, _item, _course in sorted(
                            replacement_group, key=lambda row: row[0], reverse=True
                        ):
                            normalized.pop(replace_index)
                        for candidate in candidate_group:
                            normalized.append({
                                "course_id": candidate.id,
                                "title": candidate.title,
                                "domain": candidate.domain,
                                "credits": candidate.credits or 5,
                                "recommended_semester": candidate.recommended_semester,
                                "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                                "type": candidate.cycle_component or "mandatory",
                                "selection_method": "domain_quota_group_rebalance",
                            })
                        swapped = True
                        break
                if not swapped:
                    def missing_domain_bundle(course_id: int, visiting: set | None = None):
                        visiting = visiting or set()
                        if course_id in ids:
                            return []
                        if course_id in visiting:
                            return None
                        course = courses.get(course_id)
                        if (
                            course is None
                            or (
                                course.id not in epvo_domain_index
                                and not _course_domain_matches(course, project_domains)
                            )
                        ):
                            return None
                        mapped_domain = project_domain_index(course)
                        if mapped_domain != domain_index:
                            foundation_title = _title_key(course.title)
                            foundation_tokens = (
                                "алгоритм", "algorithm", "нейрон", "neural",
                                "данн", "data", "статист", "statistic",
                                "программ", "program", "информ", "comput",
                                "математ", "math", "биоинформ", "bioinform",
                            )
                            if not any(token in foundation_title for token in foundation_tokens):
                                return None
                        bundle_courses: List[Course] = []
                        for prerequisite_id in prereq_ids_by_course.get(course_id, []):
                            prerequisite_bundle = missing_domain_bundle(
                                prerequisite_id, visiting | {course_id}
                            )
                            if prerequisite_bundle is None:
                                return None
                            bundle_courses.extend(prerequisite_bundle)
                        bundle_courses.append(course)
                        return list({value.id: value for value in bundle_courses}.values())

                    bundle_candidates = []
                    for candidate in domain_quota_candidates(domain_index):
                        if candidate.id in ids or _title_key(candidate.title) in titles:
                            continue
                        candidate_bundle = missing_domain_bundle(candidate.id)
                        if not candidate_bundle or len(candidate_bundle) > 4:
                            continue
                        bundle_credits = sum(int(value.credits or 5) for value in candidate_bundle)
                        target_credits = sum(
                            int(value.credits or 5)
                            for value in candidate_bundle
                            if project_domain_index(value) == domain_index
                        )
                        if bundle_credits <= 0 or bundle_credits > 24 or target_credits <= 0:
                            continue
                        bundle_candidates.append((candidate_bundle, bundle_credits, target_credits))
                        if len(bundle_candidates) >= 80:
                            break

                    replaceable_all = []
                    for index, item in enumerate(normalized):
                        course = courses.get(item.get("course_id"))
                        replace_domain = project_domain_index(course) if course else None
                        if (
                            course
                            and not item.get("regulatory_required")
                            and item.get("course_id") not in protected
                            and replace_domain != domain_index
                        ):
                            replaceable_all.append((index, item, course))
                    replaceable_all.sort(key=lambda row: (
                        _course_role_rank(row[2], project_domains),
                        priority_rank(row[2]),
                        int(row[1].get("recommended_semester") or 99),
                    ))
                    replaceable_all = replaceable_all[:16]
                    replacement_groups = {}
                    for size in (1, 2, 3, 4):
                        for group in combinations(replaceable_all, size):
                            group_credits = sum(int(row[1].get("credits") or 0) for row in group)
                            other_domain = project_domain_index(group[0][2])
                            if (
                                other_domain not in (0, 1)
                                or current[other_domain] - group_credits >= required[other_domain]
                            ):
                                replacement_groups.setdefault(group_credits, group)
                    for candidate_bundle, bundle_credits, target_credits in bundle_candidates:
                        replacement_group = replacement_groups.get(bundle_credits)
                        if not replacement_group:
                            continue
                        replacement_indexes = {row[0] for row in replacement_group}
                        trial = [
                            item for index, item in enumerate(normalized)
                            if index not in replacement_indexes
                        ] + [
                            {
                                "course_id": candidate.id,
                                "title": candidate.title,
                                "domain": candidate.domain,
                                "credits": candidate.credits or 5,
                                "recommended_semester": candidate.recommended_semester,
                                "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                                "type": candidate.cycle_component or "mandatory",
                                "selection_method": "domain_quota_prerequisite_bundle",
                            }
                            for candidate in candidate_bundle
                        ]
                        if not quality_preserved(trial):
                            continue
                        for replace_index, _item, _course in sorted(
                            replacement_group, key=lambda row: row[0], reverse=True
                        ):
                            normalized.pop(replace_index)
                        for candidate in candidate_bundle:
                            normalized.append({
                                "course_id": candidate.id,
                                "title": candidate.title,
                                "domain": candidate.domain,
                                "credits": candidate.credits or 5,
                                "recommended_semester": candidate.recommended_semester,
                                "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                                "type": candidate.cycle_component or "mandatory",
                                "selection_method": "domain_quota_prerequisite_bundle",
                            })
                        swapped = True
                        break
                if not swapped:
                    break
        return normalized

    def fill_domain_quota(domain_index: int) -> None:
        nonlocal total
        regulatory_selected_credits = sum(
            int(item.get("credits") or 0)
            for item in selected.values()
            if item.get("regulatory_required")
        )
        quota_base = max(0, quota_total_credits - regulatory_selected_credits)
        required = math.ceil(quota_base * min_domain_percent[domain_index] / 100)
        if required <= 0:
            return
        domain_candidates = [
            cid for cid in candidate_ids
            if cid in courses and project_domain_share(courses[cid], domain_index) > 0.0
        ]
        for cid in domain_candidates:
            if selected_domain_credits(domain_index) >= required:
                break
            additions = list({
                item["course_id"]: item
                for item in bundle(cid)
                if item["course_id"] not in selected
            }.values())
            addition_credits = sum(item["credits"] for item in additions)
            if not additions or total + addition_credits > maximum:
                continue
            for item in additions:
                reserved = dict(item)
                reserved["domain_quota_reserve"] = domain_index + 1
                reserved["selection_method"] = "domain_quota_reserve"
                selected[reserved["course_id"]] = reserved
            total = sum(item["credits"] for item in selected.values())

    # Respect the quotas entered in the project wizard before the generic fill.
    if interdisciplinary:
        fill_domain_quota(1)
    fill_domain_quota(0)

    for cid in candidate_ids:
        total, added = add_bundle_if_fits(selected, bundle(cid), maximum)
        if not added:
            continue
        if total >= target: break
    if total < target:
        if variant_type == "B":
            fallback = sorted((c for c in courses.values() if is_project_domain(c) and course_depth(c.id) < num_semesters), key=lambda c: (-role_rank(c), -scope_rank(c), c.recommended_semester or 99, c.credits or 5, c.id))
        elif variant_type == "C":
            fallback = sorted((c for c in courses.values() if is_project_domain(c) and course_depth(c.id) < num_semesters), key=lambda c: (-role_rank(c), -scope_rank(c), (c.domain or "").lower(), c.recommended_semester or 99, -c.id))
        else:
            fallback = sorted((c for c in courses.values() if is_project_domain(c) and course_depth(c.id) < num_semesters), key=lambda c: (-role_rank(c), -scope_rank(c), c.recommended_semester or 99, c.credits or 5, c.id))
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
    if variant_type == "B":
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
    result = replace_redundant_bridge(result, None)
    result = _trim_to_target_credits(result, target, db)
    result = rebalance_domain_quotas(result)
    # The last trim/bridge replacement must not remove the sole real source
    # for a programme LO. Reclose gaps at the true end of selection.
    result = close_professional_lo_gaps(result)
    result = admit_real_courses(result)
    result = top_up_with_real_epvo_courses(result)
    result = top_up_with_credit_bridges(result)
    result = replace_redundant_bridge(result, None)
    result = _trim_to_target_credits(result, target, db)
    result = _fill_existing_bridge_credit_gap(result, target, db)
    result = rebalance_domain_quotas(result)
    result = _fill_existing_bridge_credit_gap(result, target, db)
    result = top_up_with_credit_bridges(result)
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
    return _unique_items_by_title(result)
