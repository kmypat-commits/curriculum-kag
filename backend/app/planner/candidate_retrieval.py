from __future__ import annotations

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

def _repair_missing_ict_competencies(
    items: List[Dict],
    project_version: ProjectVersion,
    db: Session,
) -> List[Dict]:
    """Swap in credible local foundations when scoped EPVO cards omit an ICT block."""
    constraints = project_version.project.constraints_json or {}
    requirements = _ict_competency_requirements(constraints)
    if not requirements:
        return items
    normalized = [dict(item) for item in items]
    selected_ids = {
        int(item["course_id"]) for item in normalized if item.get("course_id") is not None
    }
    selected_courses = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(selected_ids or [-1])).all()
    }
    audit = _ict_competency_audit(list(selected_courses.values()), constraints)
    if audit["passed"]:
        return normalized

    professional_lo_ids = {
        lo.id for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    }
    matches = db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version.id,
        MatchScore.lo_id.in_(professional_lo_ids or {-1}),
    ).all()
    effective_by_course: Dict[int, Dict[int, float]] = {}
    for match in matches:
        expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        score = max(float(match.score or 0.0), expert)
        if score >= 0.4:
            effective_by_course.setdefault(int(match.course_id), {})[int(match.lo_id)] = score
    candidate_ids = set(effective_by_course) - selected_ids
    candidates = db.query(Course).filter(Course.id.in_(candidate_ids or {-1})).all()
    project_domains = _project_domain_terms(project_version, db)
    # EPVO cards are valid repair candidates when they belong to the selected
    # direction/group and education level.  The previous filter rejected all
    # ``EPVO-*`` cards, which made the competency repair unable to add real
    # programming or systems courses even when EPVO contained them.
    scope_pairs = [(
        str(constraints.get("group_code") or "").strip(),
        str(constraints.get("direction_code") or "").strip(),
    )]
    if str(constraints.get("program_type") or "").lower() in {"interdisciplinary", "joint"}:
        scope_pairs.append((
            str(constraints.get("secondary_group_code") or "").strip(),
            str(constraints.get("secondary_direction_code") or "").strip(),
        ))
    epvo_candidate_ids: set[int] = set()
    epvo_candidates = db.query(EpvoDisciplineNormalized).filter(
        EpvoDisciplineNormalized.approved_course_id.in_(candidate_ids or {-1})
    ).all()
    for row in epvo_candidates:
        if not row.approved_course_id or not epvo_row_matches_education_level(
            row, constraints.get("education_level")
        ):
            continue
        groups = {str(value or "") for value in (row.group_codes or [])}
        directions = {str(value or "") for value in (row.direction_codes or [])}
        if any(
            (group and group in groups) or (direction and direction in directions)
            for group, direction in scope_pairs
        ):
            epvo_candidate_ids.add(int(row.approved_course_id))
    candidates = [
        course for course in candidates
        if _education_level_course_allowed(course, constraints.get("education_level"))
        and (
            (str(course.course_id or "").startswith("EPVO-") and course.id in epvo_candidate_ids)
            or (
                not str(course.course_id or "").startswith("EPVO-")
                and _course_domain_matches(course, project_domains)
            )
        )
    ]
    protected_ids = {
        int(prerequisite_id)
        for item in normalized
        for prerequisite_id in (item.get("prerequisites") or [])
        if prerequisite_id in selected_ids
    }

    for missing_code in list(audit["missing"]):
        alternatives = requirements[missing_code]
        block_candidates = [
            course for course in candidates
            if any(
                all(stem in str(course.title or "").casefold() for stem in stems)
                for stems in alternatives
            )
        ]
        block_candidates.sort(key=lambda course: (
            -max(effective_by_course.get(course.id, {}).values(), default=0.0),
            course.recommended_semester or 99,
            course.id,
        ))
        repaired = False
        for candidate in block_candidates:
            candidate_scores = effective_by_course.get(candidate.id, {})
            candidate_strong = {lo_id for lo_id, score in candidate_scores.items() if score >= 0.5}
            replaceable = [
                (index, item)
                for index, item in enumerate(normalized)
                if item.get("course_id") is not None
                and not item.get("regulatory_required")
                and int(item.get("course_id")) not in protected_ids
                and int(item.get("credits") or 0) == int(candidate.credits or 5)
            ]
            replaceable.sort(key=lambda pair: (
                float(pair[1].get("admission_score") or 0.0),
                -int(pair[1].get("recommended_semester") or 0),
            ))
            for index, old_item in replaceable:
                old_id = int(old_item["course_id"])
                other_strong = {
                    lo_id
                    for course_id, scores in effective_by_course.items()
                    if course_id in selected_ids and course_id != old_id
                    for lo_id, score in scores.items()
                    if score >= 0.5
                }
                old_strong = {
                    lo_id for lo_id, score in effective_by_course.get(old_id, {}).items()
                    if score >= 0.5
                }
                if not old_strong.issubset(other_strong | candidate_strong):
                    continue
                trial = [dict(item) for item in normalized]
                trial[index] = {
                    "course_id": candidate.id,
                    "title": candidate.title,
                    "domain": candidate.domain,
                    "credits": int(candidate.credits or 5),
                    "recommended_semester": candidate.recommended_semester,
                    "prerequisites": [],
                    "type": candidate.cycle_component or "mandatory",
                    "selection_method": "ict_competency_repair",
                    "competency_required": True,
                    # Keep the same auditable admission marker as other
                    # scoped EPVO selections so the final domain guard does
                    # not mistake a valid repair for a foreign course.
                    "admission_reason": "epvo_scope_and_lo",
                    "repair_reason": "missing_ict_competency_and_lo",
                    "admission_los": sorted(
                        str(lo.lo_code)
                        for lo in project_version.learning_outcomes
                        if lo.id in candidate_scores
                    ),
                    "admission_score": round(max(candidate_scores.values()), 4),
                }
                trial_courses = [
                    selected_courses.get(int(item["course_id"]))
                    if int(item["course_id"]) != candidate.id else candidate
                    for item in trial if item.get("course_id") is not None
                ]
                trial_courses = [course for course in trial_courses if course is not None]
                trial_audit = _ict_competency_audit(trial_courses, constraints)
                if len(trial_audit["missing"]) >= len(audit["missing"]):
                    continue
                normalized = trial
                selected_ids.discard(old_id)
                selected_ids.add(candidate.id)
                selected_courses.pop(old_id, None)
                selected_courses[candidate.id] = candidate
                audit = trial_audit
                repaired = True
                break
            if repaired:
                break
    return normalized

def _limit_general_course_items(
    items: List[Dict],
    courses: Dict[int, Course],
    project_domains: List[str],
    target_credits: int,
    max_percent: int = 20,
) -> List[Dict]:
    """Keep generic/domain-adjacent courses as support, not as programme core."""
    if not items:
        return items
    max_general_credits = max(0, math.floor(target_credits * max_percent / 100))
    normalized = [dict(item) for item in items]
    selected_ids = {item.get("course_id") for item in normalized if item.get("course_id") is not None}
    protected_ids = {
        prerequisite_id
        for item in normalized
        for prerequisite_id in (item.get("prerequisites") or [])
        if prerequisite_id in selected_ids
    }
    general_indexes = []
    general_credits = 0
    for index, item in enumerate(normalized):
        course_id = item.get("course_id")
        course = courses.get(course_id)
        if course and _course_curriculum_role(course, project_domains) == "general":
            credits = int(item.get("credits") or course.credits or 0)
            general_credits += credits
            if course_id not in protected_ids:
                general_indexes.append((index, credits, _course_role_rank(course, project_domains), int(course_id or 0)))
    if general_credits <= max_general_credits:
        return normalized
    remove_indexes = set()
    for index, credits, _rank, _cid in sorted(general_indexes, key=lambda row: (row[2], row[3])):
        if general_credits <= max_general_credits:
            break
        remove_indexes.add(index)
        general_credits -= credits
    return [item for index, item in enumerate(normalized) if index not in remove_indexes]

def _remap_equivalent_prerequisites(items: List[Dict], db: Session) -> List[Dict]:
    """Point prerequisite clones at the retained same-title course row."""
    normalized = [dict(item) for item in items]
    retained_by_title = {
        _title_key(item.get("title")): item.get("course_id")
        for item in normalized
        if item.get("course_id") is not None
    }
    prerequisite_ids = {
        prerequisite_id
        for item in normalized
        for prerequisite_id in (item.get("prerequisites") or [])
    }
    prerequisite_titles = {
        course.id: _title_key(course.title)
        for course in db.query(Course).filter(Course.id.in_(prerequisite_ids or [-1])).all()
    }
    selected_ids = {value for value in retained_by_title.values() if value is not None}
    for item in normalized:
        remapped = []
        for prerequisite_id in item.get("prerequisites") or []:
            replacement = retained_by_title.get(prerequisite_titles.get(prerequisite_id, ""), prerequisite_id)
            if replacement in selected_ids and replacement != item.get("course_id") and replacement not in remapped:
                remapped.append(replacement)
        item["prerequisites"] = remapped
    return normalized

def _normalize_selected_courses_for_quality(
    selected_courses: List[Dict],
    project_version: ProjectVersion,
    db: Session,
    variant_type: str,
) -> List[Dict]:
    """Make the persisted plan reflect the international-quality fix.

    Older generated variants can be valid from a credit perspective but still
    miss the explicit interdisciplinary quality bridge.  This helper applies a
    conservative, auditable normalization to every generator path:
    replace one non-prerequisite 5-credit course with the quality bridge, then
    trim a non-prerequisite elective if the plan remains above the target.
    """
    constraints = project_version.project.constraints_json or {}
    target_credits = int(constraints.get("total_credits", 240))
    quality_bridge = db.query(BridgeModule).filter(
        BridgeModule.project_version_id == project_version.id,
        BridgeModule.course_id == f"QUALITY_BRIDGE_{project_version.id}",
    ).first()

    normalized = [dict(item) for item in selected_courses]

    def total_credits() -> int:
        return sum(int(item.get("credits") or 0) for item in normalized)

    def protected_course_ids() -> set[int]:
        selected_ids = {
            item.get("course_id")
            for item in normalized
            if item.get("course_id") is not None
        }
        return {
            prerequisite_id
            for item in normalized
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in selected_ids
        }

    def relevance(course_id: int | None) -> float:
        if course_id is None:
            return 0.0
        return float(
            sum(
                float(row[0] or 0.0)
                for row in db.query(MatchScore.score)
                .filter(
                    MatchScore.project_version_id == project_version.id,
                    MatchScore.course_id == course_id,
                )
            )
        )

    if quality_bridge and not any(item.get("bridge_module_id") for item in normalized):
        bridge_credits = int(quality_bridge.credits or 5)
        protected = protected_course_ids()
        replaceable = [
            (index, item)
            for index, item in enumerate(normalized)
            if item.get("course_id") is not None
            and item.get("course_id") not in protected
            and int(item.get("credits") or 0) == bridge_credits
        ]
        if replaceable:
            replaceable.sort(
                key=lambda pair: (
                    relevance(pair[1].get("course_id")),
                    int(pair[1].get("recommended_semester") or 99),
                    int(pair[1].get("course_id") or 0),
                )
            )
            offset = {"A": 0, "B": 1, "C": 2}.get(variant_type, 0)
            replace_index, _ = replaceable[offset % min(len(replaceable), 3)]
            normalized[replace_index] = {
                "bridge_module_id": quality_bridge.id,
                "title": quality_bridge.title,
                "domain": "interdisciplinary",
                "credits": bridge_credits,
                "recommended_semester": quality_bridge.recommended_semester,
                "prerequisites": quality_bridge.prerequisites or [],
                "type": "bridge",
            }
        elif total_credits() + bridge_credits <= target_credits + max(0, int(constraints.get("credit_tolerance", TOTAL_CREDIT_TOLERANCE))):
            normalized.append({
                "bridge_module_id": quality_bridge.id,
                "title": quality_bridge.title,
                "domain": "interdisciplinary",
                "credits": bridge_credits,
                "recommended_semester": quality_bridge.recommended_semester,
                "prerequisites": quality_bridge.prerequisites or [],
                "type": "bridge",
            })

    while total_credits() > target_credits:
        excess = total_credits() - target_credits
        protected = protected_course_ids()
        removable = [
            (index, item)
            for index, item in enumerate(normalized)
            if item.get("course_id") is not None
            and item.get("course_id") not in protected
            and total_credits() - int(item.get("credits") or 0) >= target_credits
        ]
        if not removable:
            break
        removable.sort(
            key=lambda pair: (
                int(pair[1].get("credits") or 0) != excess,
                relevance(pair[1].get("course_id")),
                -int(pair[1].get("recommended_semester") or 0),
                int(pair[1].get("course_id") or 0),
            )
        )
        del normalized[removable[0][0]]

    return normalized

def _promote_epvo_priority_courses(
    items: List[Dict],
    courses: Dict[int, Course],
    prereq_ids_by_course: Dict[int, List[int]],
    is_project_domain,
    course_depth,
    num_semesters: int,
    priority_rank,
    target_credits: int,
    maximum_credits: int,
) -> List[Dict]:
    """Prefer real EPVO typical disciplines with expert evidence."""
    result = [dict(item) for item in items]
    selected_ids = {item.get("course_id") for item in result if item.get("course_id") is not None}
    selected_titles = {_title_key(item.get("title")) for item in result if item.get("title")}
    protected_ids = {
        prerequisite_id
        for item in result
        for prerequisite_id in (item.get("prerequisites") or [])
        if prerequisite_id in selected_ids
    }
    total = sum(int(item.get("credits") or 0) for item in result)
    priority_courses = sorted(
        (
            course for course in courses.values()
            if course.id not in selected_ids
            and is_project_domain(course)
            and course_depth(course.id) < num_semesters
            and priority_rank(course) > 0
            and _title_key(course.title) not in selected_titles
        ),
        key=lambda course: (
            priority_rank(course),
            len(prereq_ids_by_course.get(course.id, [])),
            -(course.recommended_semester or 99),
            -course.id,
        ),
        reverse=True,
    )

    promoted = 0
    for course in priority_courses:
        if promoted >= 30:
            break
        prereq_ids = prereq_ids_by_course.get(course.id, [])
        missing_prereqs = [pre_id for pre_id in prereq_ids if pre_id not in selected_ids]
        additions = []
        for pre_id in missing_prereqs:
            pre = courses.get(pre_id)
            if not pre or not is_project_domain(pre) or _title_key(pre.title) in selected_titles:
                additions = []
                break
            additions.append(pre)
        additions.append(course)
        bundle_credits = sum(int(candidate.credits or 5) for candidate in additions)
        if total + bundle_credits <= maximum_credits:
            for candidate in additions:
                result.append({
                    "course_id": candidate.id,
                    "title": candidate.title,
                    "domain": candidate.domain,
                    "credits": candidate.credits or 5,
                    "recommended_semester": candidate.recommended_semester,
                    "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                    "type": candidate.cycle_component or "mandatory",
                    "selection_method": "epvo_priority",
                })
                selected_ids.add(candidate.id)
                selected_titles.add(_title_key(candidate.title))
                total += int(candidate.credits or 5)
            promoted += 1
            continue
        if missing_prereqs:
            continue
        same_credit = int(course.credits or 5)
        replaceable = [
            (index, item)
            for index, item in enumerate(result)
            if item.get("course_id") is not None
            and item.get("course_id") not in protected_ids
            and int(item.get("credits") or 5) == same_credit
            and priority_rank(courses.get(item.get("course_id"))) < priority_rank(course)
        ]
        replaceable.sort(key=lambda pair: priority_rank(courses.get(pair[1].get("course_id"))))
        if not replaceable:
            continue
        index, old_item = replaceable[0]
        selected_ids.discard(old_item.get("course_id"))
        selected_titles.discard(_title_key(old_item.get("title")))
        result[index] = {
            "course_id": course.id,
            "title": course.title,
            "domain": course.domain,
            "credits": course.credits or 5,
            "recommended_semester": course.recommended_semester,
            "prerequisites": prereq_ids,
            "type": course.cycle_component or "mandatory",
            "selection_method": "epvo_priority_replacement",
        }
        selected_ids.add(course.id)
        selected_titles.add(_title_key(course.title))
        promoted += 1
    return _unique_items_by_title(result)

def _select_exact_professional_subset(
    candidates: List[Dict],
    evidence: Dict[int, tuple[int, float]],
    capacity: int,
    domain_index_by_course: Dict[int, int],
    minimum_domain_credits: tuple[int, int],
    variant_type: str = "A",
) -> List[int]:
    """Return an exact-credit subset that preserves LO and domain constraints.

    Domain credits are capped at their required minima in the state key. This
    keeps the dynamic programme bounded even for a 240-credit curriculum while
    still distinguishing every state that can change quota feasibility.
    """
    # (credits, LO mask, capped domain-1 credits, capped domain-2 credits)
    # -> several best (evidence utility, selected candidate indexes) options.
    # Retaining alternatives is essential: otherwise the exact-credit DP
    # collapses A/B/C to the same optimum even when near-equivalent curricula
    # exist. Six options keep the state bounded while preserving alternatives.
    states: Dict[tuple[int, int, int, int], List[tuple[float, List[int]]]] = {
        (0, 0, 0, 0): [(0.0, [])]
    }
    for index, item in enumerate(candidates):
        credits = int(item.get("credits") or 0)
        course_id = int(item.get("course_id") or 0)
        if credits <= 0 or credits > capacity or course_id <= 0:
            continue
        mask, utility = evidence.get(course_id, (0, 0.0))
        if utility <= 0:
            continue
        domain_index = domain_index_by_course.get(course_id)
        snapshot = [
            (key, value)
            for key, options in states.items()
            for value in options
        ]
        for (used, covered, domain1, domain2), (current_utility, indexes) in snapshot:
            new_used = used + credits
            if new_used > capacity:
                continue
            new_domain1 = domain1
            new_domain2 = domain2
            if domain_index == 0:
                new_domain1 = min(minimum_domain_credits[0], domain1 + credits)
            elif domain_index == 1:
                new_domain2 = min(minimum_domain_credits[1], domain2 + credits)
            key = (new_used, covered | mask, new_domain1, new_domain2)
            proposal = (current_utility + utility, indexes + [index])
            options = states.setdefault(key, [])
            if any(existing_indexes == proposal[1] for _, existing_indexes in options):
                continue
            options.append(proposal)
            options.sort(key=lambda row: row[0], reverse=True)
            del options[6:]

    exact = [
        (covered, domain1, domain2, value)
        for (used, covered, domain1, domain2), values in states.items()
        if used == capacity
        for value in values
    ]
    if not exact:
        return []
    compliant = [
        row for row in exact
        if row[1] >= minimum_domain_credits[0]
        and row[2] >= minimum_domain_credits[1]
    ]
    pool = compliant or exact
    maximum_coverage = max(row[0].bit_count() for row in pool)
    pool = [row for row in pool if row[0].bit_count() == maximum_coverage]
    maximum_domain_credits = max(row[1] + row[2] for row in pool)
    pool = [row for row in pool if row[1] + row[2] == maximum_domain_credits]
    best = max(pool, key=lambda row: (row[3][0], -len(row[3][1])))
    best_utility, best_indexes = best[3]
    utility_floor = best_utility - max(0.15, abs(best_utility) * 0.03)
    alternatives = [
        row for row in pool
        if row[3][1] != best_indexes and row[3][0] >= utility_floor
    ]
    if variant_type == "B" and alternatives:
        return max(alternatives, key=lambda row: (row[3][0], -len(row[3][1])))[3][1]
    if variant_type == "C" and alternatives:
        best_set = set(best_indexes)
        return max(
            alternatives,
            key=lambda row: (
                len(best_set.symmetric_difference(row[3][1])),
                row[3][0],
            ),
        )[3][1]
    return best_indexes

def _fit_real_professional_block_after_goso(
    items: List[Dict],
    project_version: ProjectVersion,
    db: Session,
    variant_type: str = "A",
) -> List[Dict]:
    """Fit the post-GOSO professional remainder with whole real courses.

    The general trimmer cannot know that a 155-credit doctoral regulatory
    block leaves an exact 25-credit professional envelope.  Greedy trimming
    used to keep an arbitrary 13-credit subset and fill the remainder with
    bridges.  This bounded dynamic programme maximises real professional LO
    coverage first, evidence second, at the exact remaining credit total.
    """
    constraints = project_version.project.constraints_json or {}
    if str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() != "KZ":
        return items
    target = int(constraints.get("total_credits", 240))
    regulatory = [dict(item) for item in items if item.get("regulatory_required")]
    if not regulatory:
        return items
    capacity = target - sum(int(item.get("credits") or 0) for item in regulatory)
    if capacity <= 0:
        return regulatory
    candidates = _unique_items_by_title([
        dict(item) for item in items
        if item.get("course_id") is not None and not item.get("regulatory_required")
    ])
    if not candidates:
        return items

    professional_los = [
        lo for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    ]
    lo_bit = {lo.id: 1 << index for index, lo in enumerate(professional_los)}
    evidence: Dict[int, tuple[int, float]] = {}
    candidate_ids = [int(item["course_id"]) for item in candidates]
    for match in db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version.id,
        MatchScore.course_id.in_(candidate_ids or [-1]),
        MatchScore.lo_id.in_(list(lo_bit) or [-1]),
    ).all():
        expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        score = max(float(match.score or 0.0), expert)
        if score < 0.4:
            continue
        mask, value = evidence.get(int(match.course_id), (0, 0.0))
        strong_mask = lo_bit[match.lo_id] if score >= 0.5 else 0
        evidence[int(match.course_id)] = (mask | strong_mask, value + score)

    project_domains = [
        str(project_version.project.domain1 or "").casefold().strip(),
        str(project_version.project.domain2 or "").casefold().strip(),
    ]
    primary_group = str(constraints.get("group_code") or "").strip()
    secondary_group = str(constraints.get("secondary_group_code") or "").strip()
    primary_direction = str(constraints.get("direction_code") or "").strip()
    secondary_direction = str(constraints.get("secondary_direction_code") or "").strip()
    scope_evidence: Dict[int, List[int]] = {}
    for row in db.query(EpvoDisciplineNormalized).filter(
        EpvoDisciplineNormalized.approved_course_id.in_(candidate_ids or [-1])
    ).all():
        row_groups = set(row.group_codes or [])
        row_directions = set(row.direction_codes or [])
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
        if row.approved_course_id and (primary_scope or secondary_scope):
            values = scope_evidence.setdefault(int(row.approved_course_id), [0, 0])
            values[0] = max(values[0], primary_scope)
            values[1] = max(values[1], secondary_scope)
    domain_index_by_course = {
        course_id: 1 if secondary > primary else 0
        for course_id, (primary, secondary) in scope_evidence.items()
    }
    for item in candidates:
        course_id = int(item.get("course_id") or 0)
        if course_id in domain_index_by_course:
            continue
        item_domain = str(item.get("domain") or "").casefold().strip()
        for domain_index, domain in enumerate(project_domains):
            if domain and (domain in item_domain or item_domain in domain):
                domain_index_by_course[course_id] = domain_index
                break

    interdisciplinary = (
        str(constraints.get("program_type") or "standard").lower()
        in {"interdisciplinary", "joint"}
    )
    tolerance = max(
        0.0, float(constraints.get("domain_quota_tolerance_credits", 3) or 0)
    )
    percentages = (
        max(0.0, float(constraints.get("min_domain1_percent") or 0)),
        max(0.0, float(constraints.get("min_domain2_percent") or 0))
        if interdisciplinary else 0.0,
    )
    minimum_domain_credits = tuple(
        max(0, math.ceil(capacity * percentage / 100.0 - tolerance - 1e-9))
        for percentage in percentages
    )
    # The first selector may reserve real EPVO courses to satisfy an
    # interdisciplinary quota.  The exact post-GOSO fitter must retain those
    # reservations; otherwise it silently replaces them with higher-scoring
    # primary-domain courses and the final independent verifier finds a
    # secondary-domain deficit.
    locked_indexes: List[int] = [
        index for index, item in enumerate(candidates)
        if item.get("domain_quota_reserve")
    ]
    competency_requirements = _ict_competency_requirements(constraints)
    if competency_requirements:
        candidate_courses = {
            course.id: course
            for course in db.query(Course).filter(Course.id.in_(candidate_ids or [-1])).all()
        }
        regulatory_ids = {
            int(item["course_id"]) for item in regulatory
            if item.get("course_id") is not None
        }
        regulatory_courses = [
            course for course in db.query(Course).filter(
                Course.id.in_(regulatory_ids or {-1})
            ).all()
        ]

        def blocks_for_title(title: str | None) -> set[str]:
            text = str(title or "").casefold()
            return {
                code for code, alternatives in competency_requirements.items()
                if any(all(stem in text for stem in stems) for stems in alternatives)
            }

        covered_blocks = {
            code
            for course in regulatory_courses
            for code in blocks_for_title(course.title)
        }
        missing_blocks = set(competency_requirements) - covered_blocks
        locked_credits = 0
        while missing_blocks:
            options = []
            for index, item in enumerate(candidates):
                if index in locked_indexes:
                    continue
                course_id = int(item.get("course_id") or 0)
                course = candidate_courses.get(course_id)
                if not course or course_id not in evidence:
                    continue
                newly_covered = blocks_for_title(course.title) & missing_blocks
                credits = int(item.get("credits") or 0)
                if not newly_covered or locked_credits + credits > capacity:
                    continue
                options.append((
                    len(newly_covered),
                    float(evidence[course_id][1]),
                    -credits,
                    -course_id,
                    index,
                    newly_covered,
                ))
            if not options:
                break
            *_rank, index, newly_covered = max(options)
            locked_indexes.append(index)
            locked_credits += int(candidates[index].get("credits") or 0)
            missing_blocks -= newly_covered

    locked = [dict(candidates[index]) for index in locked_indexes]
    for item in locked:
        if item.get("competency_required"):
            item["selection_method"] = "ict_competency_exact_fit"
    locked_ids = {int(item["course_id"]) for item in locked}
    remaining_candidates = [
        item for item in candidates if int(item.get("course_id") or 0) not in locked_ids
    ]
    locked_domain_credits = [0, 0]
    for item in locked:
        domain_index = domain_index_by_course.get(int(item["course_id"]))
        if domain_index in (0, 1):
            locked_domain_credits[domain_index] += int(item.get("credits") or 0)
    remaining_minimum_domain_credits = tuple(
        max(0, minimum_domain_credits[index] - locked_domain_credits[index])
        for index in (0, 1)
    )
    best_indexes = _select_exact_professional_subset(
        remaining_candidates,
        evidence,
        capacity - sum(int(item.get("credits") or 0) for item in locked),
        domain_index_by_course,
        remaining_minimum_domain_credits,
        variant_type,
    )
    if not best_indexes:
        locked = []
        remaining_candidates = candidates
        best_indexes = _select_exact_professional_subset(
            candidates,
            evidence,
            capacity,
            domain_index_by_course,
            minimum_domain_credits,
            variant_type,
        )
    if not best_indexes:
        return items
    selected = [remaining_candidates[index] for index in best_indexes]
    for item in selected:
        item["selection_method"] = "goso_professional_exact_fit"
    return _unique_items_by_title([*regulatory, *locked, *selected])
