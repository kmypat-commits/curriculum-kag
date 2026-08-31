from __future__ import annotations

from itertools import combinations
import math
import re
import time
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
from app.planner.variant_assembly import add_bundle_if_fits
from app.planner.variant_ranking import ranked_unique_candidate_ids

def _diversify_variant_items(
    items: List[Dict],
    project_version: ProjectVersion,
    db: Session,
    variant_type: str,
    max_swaps: int = 2,
) -> List[Dict]:
    """Keep A/B/C as real alternatives when optimization converges.

    The replacement is conservative: same credits, same project domains, no
    prerequisites, no duplicate title, and no removal of a selected prerequisite.
    """
    if variant_type not in {"B", "C"}:
        return items
    deadline = time.perf_counter() + 10.0
    project_domains = _project_domain_terms(project_version, db)
    cyber_forensics_program = (
        any("it" in d or "информ" in d or "computer" in d or "кибер" in d for d in project_domains)
        and any("forensic" in d or "криминал" in d or "расслед" in d for d in project_domains)
    )
    def is_project_domain(course: Course) -> bool:
        if not _course_domain_matches(course, project_domains):
            return False
        if cyber_forensics_program:
            return _course_curriculum_role(course, project_domains) == "core"
        return True

    normalized = [dict(item) for item in items]
    selected_ids = {item.get("course_id") for item in normalized if item.get("course_id") is not None}
    selected_titles = {_title_key(item.get("title")) for item in normalized if item.get("title")}
    protected_ids = {
        prerequisite_id
        for item in normalized
        for prerequisite_id in (item.get("prerequisites") or [])
        if prerequisite_id in selected_ids
    }
    if not selected_ids:
        return normalized

    match_max_by_course = {
        int(row.course_id): float(row.max_score or 0.0)
        for row in db.query(MatchScore.course_id, func.max(MatchScore.score).label("max_score"))
        .filter(MatchScore.project_version_id == project_version.id)
        .group_by(MatchScore.course_id)
        .all()
    }
    professional_lo_codes = {
        int(lo.id): str(lo.lo_code)
        for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    }
    admission_by_course: Dict[int, Dict[str, object]] = {}
    scores_by_course: Dict[int, Dict[str, float]] = {}
    for match in db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version.id
    ).all():
        lo_code = professional_lo_codes.get(int(match.lo_id))
        if not lo_code:
            continue
        expert_score = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        score = max(float(match.score or 0.0), expert_score)
        if score < 0.4:
            continue
        scores_by_course.setdefault(int(match.course_id), {})[lo_code] = max(
            scores_by_course.get(int(match.course_id), {}).get(lo_code, 0.0),
            score,
        )
        row = admission_by_course.setdefault(
            int(match.course_id), {"los": set(), "score": 0.0}
        )
        row["los"].add(lo_code)
        row["score"] = max(float(row["score"]), score)

    def preserves_professional_coverage(course_ids: set[int]) -> bool:
        for lo_code in professional_lo_codes.values():
            scores = [
                scores_by_course.get(int(course_id), {}).get(lo_code, 0.0)
                for course_id in course_ids
            ]
            scores = [score for score in scores if score > 0]
            if max(scores, default=0.0) + 1e-9 < 0.5:
                return False
            product = 1.0
            for score in scores:
                product *= 1.0 - max(0.0, min(1.0, score))
            if 1.0 - product + 1e-9 < float(settings.COVERAGE_THRESHOLD):
                return False
        return True

    def preserves_core_competencies(course_ids: set[int]) -> bool:
        """Do not diversify by removing the only RK/ICT competency block."""
        from app.planner.verifier import _ict_competency_audit
        courses = [course for course in db.query(Course).filter(Course.id.in_(course_ids)).all()]
        audit = _ict_competency_audit(courses, project_version.project.constraints_json or {})
        return bool(audit.get("passed"))
    alternatives_by_credit: Dict[int, List[Course]] = {}
    from app.planner.verifier import _ict_competency_requirements
    competency_requirements = _ict_competency_requirements(project_version.project.constraints_json or {})
    def course_matches_competency(course: Course, alternatives) -> bool:
        text = str(course.title or '').casefold()
        return any(
            all(stem.casefold() in text for stem in stems)
            for stems in alternatives
        )
    # The match/admission maps already define the only courses that can be
    # valid diversification candidates.  Loading the entire catalogue here
    # (twice for interdisciplinary competency checks) made variant B spend
    # minutes materializing thousands of unrelated ORM rows.
    candidate_course_ids = set(admission_by_course).intersection(match_max_by_course)
    catalogue_courses = db.query(Course).filter(
        Course.id.in_(candidate_course_ids or {-1})
    ).all()
    for course in catalogue_courses:
        key = _title_key(course.title)
        if (
            course.id not in selected_ids
            and course.id in match_max_by_course
            and course.id in admission_by_course
            and key not in selected_titles
            and is_project_domain(course)
            and match_max_by_course.get(course.id, 0.0) >= 0.4
            and not course.prerequisites
        ):
            alternatives_by_credit.setdefault(int(course.credits or 5), []).append(course)
    # Ensure a variant cannot lose the only course representing a required
    # core competency while seeking diversity.  These candidates are still
    # subject to the same score, level, credit and LO checks below.
    for alternatives in competency_requirements.values():
        if time.perf_counter() >= deadline:
            return normalized
        for course in catalogue_courses:
            key = _title_key(course.title)
            if (
                course.id not in selected_ids
                and key not in selected_titles
                and course.id in admission_by_course
                and match_max_by_course.get(course.id, 0.0) >= 0.4
                and course_matches_competency(course, alternatives)
            ):
                alternatives_by_credit.setdefault(int(course.credits or 5), []).append(course)
    for alternatives in alternatives_by_credit.values():
        if time.perf_counter() >= deadline:
            return normalized
        alternatives.sort(
            key=lambda course: (
                course.recommended_semester or 99,
                course.id if variant_type == "C" else -course.id,
            )
        )
    pair_candidates = [
        course
        for values in alternatives_by_credit.values()
        for course in values
    ]
    pair_candidates.sort(
        key=lambda course: (
            int(course.credits or 5),
            course.id if variant_type == "C" else -course.id,
        ),
        reverse=(variant_type == "C"),
    )
    pair_candidates = pair_candidates[:30]

    removable = [
        (index, item)
        for index, item in enumerate(normalized)
        if item.get("course_id") is not None
        and item.get("course_id") not in protected_ids
        and not item.get("domain_quota_reserve")
        and not (
            len(project_domains) > 1
            and domain_label_matches(item.get("domain"), [project_domains[1]])
        )
    ]
    removable.sort(key=lambda pair: int(pair[1].get("course_id") or 0), reverse=(variant_type == "C"))

    swaps = 0
    for index, item in removable:
        if time.perf_counter() >= deadline:
            return normalized
        if swaps >= max_swaps:
            break
        credits = int(item.get("credits") or 5)
        candidate = None
        while alternatives_by_credit.get(credits):
            possible = alternatives_by_credit[credits].pop(0)
            possible_title = _title_key(possible.title)
            trial_ids = {
                int(value) for value in selected_ids
                if value is not None and int(value) != int(item.get("course_id") or 0)
            } | {int(possible.id)}
            if (
                possible.id not in selected_ids
                and possible_title not in selected_titles
                and _education_level_course_allowed(
                    possible,
                    (project_version.project.constraints_json or {}).get("education_level"),
                )
                and preserves_professional_coverage(trial_ids)
                and preserves_core_competencies(trial_ids)
            ):
                candidate = possible
                break
        if candidate is None:
            continue
        selected_ids.discard(item.get("course_id"))
        selected_ids.add(candidate.id)
        selected_titles.discard(_title_key(item.get("title")))
        selected_titles.add(_title_key(candidate.title))
        normalized[index] = {
            "course_id": candidate.id,
            "title": candidate.title,
            "domain": candidate.domain,
            "credits": candidate.credits or 5,
            "recommended_semester": candidate.recommended_semester,
            "prerequisites": [],
            "type": candidate.cycle_component or "mandatory",
            "selection_method": item.get("selection_method") or "diversified_alternative",
            "admission_reason": "diversified_course_and_lo",
            "admission_los": sorted(admission_by_course[candidate.id]["los"]),
            "admission_score": round(float(admission_by_course[candidate.id]["score"]), 4),
        }
        swaps += 1

    # A tight doctoral 25-credit envelope may have no safe one-course swap:
    # every selected course can be the sole strong source for one LO. Two
    # coordinated replacements can still form a genuinely different variant
    # while preserving total credits and all probabilistic LO constraints.
    if swaps == 0 and variant_type == "C":
        removable_pairs = list(combinations(removable[:12], 2))
        candidate_pairs = list(combinations(pair_candidates, 2))
        candidate_pairs.sort(
            key=lambda pair: (pair[0].id + pair[1].id, pair[0].id, pair[1].id),
            reverse=True,
        )
        diversified = False
        for old_pair in removable_pairs:
            old_ids = {int(row[1].get("course_id") or 0) for row in old_pair}
            old_credits = sum(int(row[1].get("credits") or 0) for row in old_pair)
            for new_pair in candidate_pairs:
                if sum(int(course.credits or 5) for course in new_pair) != old_credits:
                    continue
                if len({_title_key(course.title) for course in new_pair}) != 2:
                    continue
                if any(
                    course.id in selected_ids
                    or _title_key(course.title) in selected_titles
                    or not _education_level_course_allowed(
                        course,
                        (project_version.project.constraints_json or {}).get("education_level"),
                    )
                    for course in new_pair
                ):
                    continue
                trial_ids = {
                    int(value) for value in selected_ids
                    if value is not None and int(value) not in old_ids
                } | {int(course.id) for course in new_pair}
                if not preserves_professional_coverage(trial_ids) or not preserves_core_competencies(trial_ids):
                    continue
                for (item_index, old_item), course in zip(old_pair, new_pair):
                    normalized[item_index] = {
                        "course_id": course.id,
                        "title": course.title,
                        "domain": course.domain,
                        "credits": int(course.credits or 5),
                        "recommended_semester": course.recommended_semester,
                        "prerequisites": [],
                        "type": course.cycle_component or "mandatory",
                        "selection_method": "diversified_pair_alternative",
                        "admission_reason": "diversified_course_and_lo",
                        "admission_los": sorted(admission_by_course[course.id]["los"]),
                        "admission_score": round(float(admission_by_course[course.id]["score"]), 4),
                    }
                diversified = True
                break
            if diversified:
                break
    return normalized
