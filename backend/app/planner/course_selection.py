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


def _bridge_item(module: BridgeModule) -> Dict:
    item = {
        "bridge_module_id": module.id,
        "title": module.title,
        "domain": "interdisciplinary",
        "credits": module.credits or 5,
        "recommended_semester": module.recommended_semester,
        "prerequisites": module.prerequisites or [],
        "type": "bridge",
    }
    if (module.course_id or "").startswith(("CORE_BRIDGE_", "SECONDARY_")):
        recommended = int(module.recommended_semester or 1)
        item["latest_semester"] = recommended + (
            2 if (module.course_id or "").startswith("CORE_BRIDGE_") else 1
        )
    return item


def _force_bridge_item(
    items: List[Dict],
    module: BridgeModule | None,
    variant_type: str = "A",
    target_credits: int | None = None,
) -> List[Dict]:
    if module is None or any(item.get("bridge_module_id") == module.id for item in items):
        return items
    normalized = [dict(item) for item in items]
    protected_course_ids = {
        prerequisite_id
        for item in normalized
        for prerequisite_id in (item.get("prerequisites") or [])
    }
    bridge = _bridge_item(module)
    current_total = sum(int(item.get("credits") or 0) for item in normalized)
    gap = (target_credits - current_total) if target_credits is not None else 0
    if target_credits is not None and gap >= 3:
        credits = min(int(module.credits or 5), gap)
        if 0 < gap - credits < 3:
            credits = gap - 3
        if credits >= 3:
            bridge["credits"] = credits
            normalized.append(bridge)
            return normalized
    if (
        target_credits is not None
        and current_total + int(module.credits or 5) <= target_credits
    ):
        normalized.append(bridge)
        return normalized
    same_credit = [
        (index, item) for index, item in enumerate(normalized)
        if item.get("course_id") is not None
        and not item.get("regulatory_required")
        and not item.get("competency_required")
        and item.get("course_id") not in protected_course_ids
        and int(item.get("credits") or 0) == int(module.credits or 5)
    ]
    replaceable = same_credit or [
        (index, item) for index, item in enumerate(normalized)
        if item.get("course_id") is not None
        and not item.get("regulatory_required")
        and not item.get("competency_required")
        and item.get("course_id") not in protected_course_ids
    ]
    if replaceable:
        offset = {"A": 0, "B": 1, "C": 2}.get(variant_type, 0)
        replace_index, replaced = replaceable[offset % len(replaceable)]
        bridge["credits"] = int(replaced.get("credits") or module.credits or 5)
        normalized[replace_index] = bridge
    else:
        normalized.append(bridge)
    return normalized
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
    for course in db.query(Course).all():
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
        for course in db.query(Course).all():
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
        if item.get("course_id") is not None and item.get("course_id") not in protected_ids
    ]
    removable.sort(key=lambda pair: int(pair[1].get("course_id") or 0), reverse=(variant_type == "C"))

    swaps = 0
    for index, item in removable:
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


def _ensure_foundation_capacity(
    selected_courses: List[Dict],
    project_version: ProjectVersion,
    db: Session,
) -> List[Dict]:
    """Replace safe late electives with prerequisite-free foundation modules.

    A curriculum cannot have a balanced first semester when nearly every
    selected course depends on the same small foundation.  The replacement
    preserves total credits and explicitly marks the generated modules for
    semester one.
    """
    constraints = project_version.project.constraints_json or {}
    nominal = int(constraints.get("max_credits_per_semester", 30))
    normalized = [dict(item) for item in selected_courses]
    selected_ids = {item.get("course_id") for item in normalized if item.get("course_id") is not None}
    protected = {
        prerequisite
        for item in normalized
        for prerequisite in (item.get("prerequisites") or [])
        if prerequisite in selected_ids
    }
    foundation_credits = sum(
        int(item.get("credits") or 0)
        for item in normalized
        if item.get("course_id") is not None and not (item.get("prerequisites") or [])
        or item.get("latest_semester") == 1
    )
    deficit = max(0, nominal - foundation_credits)
    target_credits = int(constraints.get("total_credits", 240))
    credit_gap = max(0, target_credits - sum(int(item.get("credits") or 0) for item in normalized))
    existing_bridges = sum(1 for item in normalized if item.get("bridge_module_id") is not None)
    slots = max(0, int(constraints.get("max_new_courses", 5)) - existing_bridges)
    if deficit <= 0 or slots <= 0 or not constraints.get("allow_new_courses", True):
        return normalized

    replacement_needed = max(0, deficit - credit_gap)
    candidates = [
        (index, item)
        for index, item in enumerate(normalized)
        if item.get("course_id") is not None
        and item.get("course_id") not in protected
        and (item.get("prerequisites") or [])
    ]
    # Exact subset-sum keeps the curriculum credit total unchanged.
    choices = {0: []}
    for index, item in candidates:
        credits = int(item.get("credits") or 0)
        for subtotal, indexes in list(choices.items())[::-1]:
            value = subtotal + credits
            if value <= replacement_needed and value not in choices:
                choices[value] = indexes + [index]
    replacement_credits = max(choices)
    module_credits = min(deficit, credit_gap + replacement_credits)
    if module_credits <= 0:
        return normalized
    indexes_to_remove = set(choices[replacement_credits])
    normalized = [item for index, item in enumerate(normalized) if index not in indexes_to_remove]
    desired_count = min(slots, max(1, math.ceil(module_credits / 7)))
    modules = ensure_credit_bridge_modules(
        project_version,
        db,
        module_credits,
        slots,
        desired_count=desired_count,
    )
    added_items = []
    for module in modules:
        item = {
            "bridge_module_id": module.id,
            "title": module.title,
            "domain": "interdisciplinary",
            "credits": module.credits or 5,
            "recommended_semester": 1,
            "latest_semester": 1,
            "prerequisites": [],
            "type": "bridge",
        }
        normalized.append(item)
        added_items.append((module, item))
    shortfall = max(0, target_credits - sum(int(item.get("credits") or 0) for item in normalized))
    for module, item in reversed(added_items):
        if shortfall <= 0:
            break
        room = max(0, 7 - int(item["credits"]))
        increase = min(room, shortfall)
        item["credits"] += increase
        module.credits = item["credits"]
        shortfall -= increase
    return normalized


def _trim_to_target_credits(items: List[Dict], target_credits: int, db: Session) -> List[Dict]:
    """Prefer exact total credits without breaking prerequisite closure."""
    normalized = [dict(item) for item in items]

    def total() -> int:
        return sum(int(item.get("credits") or 0) for item in normalized)

    for item in sorted(
        (item for item in normalized if item.get("bridge_module_id") is not None),
        key=lambda row: int(row.get("credits") or 0),
        reverse=True,
    ):
        excess = total() - target_credits
        if excess <= 0:
            break
        current = int(item.get("credits") or 0)
        reduction = min(excess, max(0, current - 3))
        if reduction <= 0:
            continue
        item["credits"] = current - reduction
        module = db.query(BridgeModule).filter(BridgeModule.id == item["bridge_module_id"]).first()
        if module:
            module.credits = item["credits"]

    # A repository discipline is an atomic approved unit: its typical credit
    # value must not be silently rewritten to make the arithmetic fit.  Only a
    # generated bridge may flex within its explicit 3--7 credit envelope.
    # Real courses are removed/replaced as whole units below.

    while total() > target_credits:
        excess = total() - target_credits
        selected_ids = {item.get("course_id") for item in normalized if item.get("course_id") is not None}
        protected = {
            prerequisite_id
            for item in normalized
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in selected_ids
        }
        removable = [
            (index, item)
            for index, item in enumerate(normalized)
            if item.get("course_id") is not None
            and not item.get("regulatory_required")
            # A competency repair is a deliberate quality constraint, not a
            # low-priority elective.  Never trim it merely to close a credit
            # gap; bridge credits are adjusted before removing core evidence.
            and item.get("selection_method") != "ict_competency_repair"
            and item.get("course_id") not in protected
            and int(item.get("credits") or 0) <= excess
            and total() - int(item.get("credits") or 0) >= target_credits
        ]
        if not removable:
            break
        removable.sort(key=lambda pair: (
            int(pair[1].get("credits") or 0) != excess,
            int(pair[1].get("recommended_semester") or 99),
            int(pair[1].get("course_id") or 0),
        ))
        del normalized[removable[0][0]]

    return _unique_items_by_title(normalized)


def _fill_existing_bridge_credit_gap(
    items: List[Dict], target_credits: int, db: Session
) -> List[Dict]:
    """Use the explicit 3--7 credit bridge envelope for a residual gap.

    Late prerequisite/domain repairs can remove a real course after the last
    bridge-slot check. Adding another module would violate ``max_new_courses``;
    increasing an existing bridge is the safe atomic repair and keeps the plan
    at its requested total without changing real-course credits.
    """
    normalized = [dict(item) for item in items]
    gap = max(0, int(target_credits) - sum(int(item.get("credits") or 0) for item in normalized))
    for item in reversed(normalized):
        if gap <= 0 or item.get("bridge_module_id") is None:
            continue
        room = max(0, 7 - int(item.get("credits") or 0))
        increase = min(room, gap)
        if increase <= 0:
            continue
        item["credits"] = int(item.get("credits") or 0) + increase
        module = db.query(BridgeModule).filter(BridgeModule.id == item["bridge_module_id"]).first()
        if module:
            module.credits = item["credits"]
        gap -= increase
    return normalized


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
    locked_indexes: List[int] = []
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
        item["competency_required"] = True
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
    # Filled from normalized EPVO rows that match both the selected scope and
    # the programme education level. A high semantic score must never allow a
    # bachelor-only catalogue card into a master's/doctoral curriculum.
    epvo_level_scope_allowed_ids: set[int] = set()

    min_general_lo_evidence = 0.55

    def is_project_domain(course: Course) -> bool:
        if not _education_level_course_allowed(course, constraints.get("education_level")):
            return False
        if (
            professional_scope
            and _has_foreign_professional_title(course, project_domains)
        ):
            return False
        if (
            interdisciplinary_professional
            and not _is_it_medicine_support_course(course, project_domains)
        ):
            return False
        course_code = str(course.course_id or "")
        if course_code.startswith("AI-CONFIRMED-") and not course_code.startswith(f"AI-CONFIRMED-{project_version_id}-"):
            # Expert-confirmed synthetic replacements belong to one project;
            # they must never leak into another curriculum through the global
            # Course table.
            return False
        if course_code.startswith("EPVO-") and course.id not in epvo_level_scope_allowed_ids:
            return False
        # Canonical EPVO courses can be shared by several programmes and keep
        # the global domain label of the first imported row. Exact selected
        # EPVO group/direction evidence is therefore authoritative here.
        if course.id not in epvo_domain_index and not _course_domain_matches(course, project_domains):
            return False
        if professional_scope and not str(course.course_id or "").startswith("GOSO-KZ-"):
            evidence = aggregates.get(course.id, {})
            if (
                epvo_professional_scope
                and str(course.course_id or "").startswith("EPVO-")
                and scope_rank(course) <= 0
                and float(evidence.get("max") or 0.0) < 0.55
            ):
                return False
            # Domain membership alone is insufficient: a medical or IT course
            # may still be irrelevant to this programme's stated outcomes.
            if (
                float(evidence.get("max") or 0.0) < 0.4
                and float(evidence.get("expert") or 0.0) < 0.5
                and not course_code.startswith(f"AI-CONFIRMED-{project_version_id}-")
            ):
                return False
        if cyber_forensics_program:
            return _course_curriculum_role(course, project_domains) == "core"
        if professional_scope and _course_curriculum_role(course, project_domains) == "general":
            evidence = aggregates.get(course.id, {})
            # In interdisciplinary professional programmes generic catalogue
            # items (languages, history, entrepreneurship, etc.) must not fill
            # the curriculum unless they have at least a weak explicit LO link.
            # Otherwise the fallback stage can reach the credit target with
            # courses that are formally in an EPVO group but pedagogically
            # unrelated to the programme outcomes.
            if float(evidence.get("max") or 0.0) < min_general_lo_evidence:
                return False
        return True

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
        mapped = epvo_domain_index.get(course.id)
        if mapped in (0, 1):
            return mapped
        domain = (course.domain or "").lower().strip()
        for index, project_domain in enumerate(project_domains):
            if project_domain and (project_domain in domain or domain in project_domain):
                return index
        return None

    weights = {lo.id: lo.weight or 1.0 for lo in version.learning_outcomes}
    lo_codes_by_id = {lo.id: lo.lo_code for lo in version.learning_outcomes}
    aggregates: Dict[int, Dict] = {}
    for match in db.query(MatchScore).filter(MatchScore.project_version_id == project_version_id).all():
        data = aggregates.setdefault(match.course_id, {
            "sum": 0.0, "los": set(), "lo_codes": set(), "credible_lo_codes": set(),
            "professional_lo_codes": set(), "max": 0.0, "expert": 0.0,
        })
        data["sum"] += match.score * weights.get(match.lo_id, 1.0)
        data["los"].add(match.lo_id)
        if lo_codes_by_id.get(match.lo_id):
            data["lo_codes"].add(lo_codes_by_id[match.lo_id])
        expert_value = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        effective_value = max(float(match.score or 0.0), expert_value)
        lo_code = str(lo_codes_by_id.get(match.lo_id) or "")
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
        return epvo_scope_by_id.get(course.id, epvo_scope.get(_title_key(course.title), 0))
    def priority_rank(course: Course) -> int:
        if course is None:
            return 0
        return epvo_priority_by_id.get(course.id, epvo_priority.get(_title_key(course.title), 0))
    def semester_stability_rank(course: Course | None) -> float:
        """Prefer candidates whose scoped EPVO semester evidence is stable.

        This is deliberately a secondary rank component: LO evidence, expert
        support, scope and domain relevance remain dominant. A zero value means
        that no scoped semester evidence is available and therefore never
        penalizes a candidate by itself.
        """
        if course is None:
            return 0.0
        values = []
        course_code = str(course.course_id or "")
        if course_code.startswith("EPVO-"):
            try:
                values = epvo_semester_values.get(int(course_code.split("-", 1)[1]), [])
            except (TypeError, ValueError):
                values = []
        if not values:
            return 0.0
        return -float(max(values) - min(values)) + min(0.25, len(values) / 100.0)
    def role_rank(course: Course | None) -> int:
        return _course_role_rank(course, project_domains)

    domain_text = " ".join(project_domains).lower()
    ict_programme = any(marker in domain_text for marker in ("информац", "коммуникац", "it", "computer", "software", "digital", "кибер"))
    medical_programme = any(marker in domain_text for marker in ("медицин", "здрав", "clinical", "health"))
    agro_programme = any(marker in domain_text for marker in ("агро", "сельск", "растен", "почв"))

    def has_foreign_scope_conflict(course: Course) -> bool:
        text = _title_key(" ".join(str(value or "") for value in (
            course.title, course.description, course.domain,
        )))
        topic_groups = (
            (("химич", "химия", "chemical", "chemistry"), ("хим", "chemical", "chemistry")),
            (("нефт", "газов", "petroleum", "oil and gas"), ("нефт", "газ", "petroleum")),
            (("горн", "геолог", "mining", "geology"), ("горн", "геолог", "mining")),
            (("медицин", "клинич", "пациент", "medical", "clinical"), ("медицин", "здрав", "medical", "health")),
            (("агро", "сельск", "растен", "почв", "crop", "soil"), ("агро", "сельск", "растен", "почв")),
            (("ветерин", "veterinary"), ("ветерин", "veterinary")),
            (("строител", "civil engineering", "construction"), ("строител", "construction")),
        )
        return any(
            any(marker in text for marker in topic_markers)
            and not any(marker in domain_text for marker in allowed_domain_markers)
            for topic_markers, allowed_domain_markers in topic_groups
        )

    def course_matches_scope_theme(course: Course) -> bool:
        if has_foreign_scope_conflict(course):
            return False
        text = " ".join(str(value or "") for value in (course.title, course.description, course.domain)).lower()
        if ict_programme:
            if any(marker in text for marker in (
                "здоров", "здравоохран", "пациент", "стоматолог", "клинич",
                "физи", "лабораторная физика", "теоретическая физика",
                "электродинами", "скалярн", "калибровоч",
                "философ", "общекультур", "лингвист", "языкозн",
            )):
                return any(marker in text for marker in (
                    "информац", "цифр", "программир", "разработк", "алгоритм", "данные", "данных", "база данных",
                    "кибер", "криптограф", "software", "digital", "data", "computer", "algorithm",
                ))
            return any(marker in text for marker in (
                "информац", "цифр", "программир", "разработк", "алгоритм", "данные", "данных", "база данных",
                "сеть", "кибер", "криптограф", "искусствен", "машинн", "software",
                "digital", "data", "computer", "algorithm", "network", "security",
                "математ", "алгебр", "исчислен", "статист", "вероятност", "дискрет",
                "логик", "оптимизац", "calculus", "algebra", "statistics", "probability",
            ))
        if medical_programme:
            return any(marker in text for marker in ("медицин", "клинич", "пациент", "здоров", "анатом", "физиолог", "фармак", "clinical", "health", "medical"))
        if agro_programme:
            return any(marker in text for marker in ("агро", "сельск", "растен", "почв", "урож", "животн", "agro", "crop", "soil"))
        return True

    def has_strong_exact_scope_evidence(course: Course) -> bool:
        """Let exact EPVO group evidence override a shallow keyword mismatch."""
        evidence = aggregates.get(course.id, {})
        return (
            not has_foreign_scope_conflict(course)
            and
            scope_rank(course) >= 3
            and bool(evidence.get("professional_lo_codes"))
            and float(evidence.get("max") or 0.0) >= 0.5
        )

    def admit_real_courses(items: List[Dict]) -> List[Dict]:
        """Final evidence gate shared by every A/B/C selection path.

        Credits and a high rank are not sufficient. Every real non-regulatory
        discipline must have a credible programme LO and pass the selected
        EPVO level/scope. Bridges are kept explicit and are never disguised as
        real-course evidence.
        """
        admitted: List[Dict] = []
        jurisdiction_kz = str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() == "KZ"
        for raw_item in items:
            item = dict(raw_item)
            course_id = item.get("course_id")
            if course_id is None:
                admitted.append(item)
                continue
            course = courses.get(int(course_id))
            if course is None or _is_component_placeholder_title(_title_key(item.get("title") or course.title)):
                continue
            course_code = str(course.course_id or "")
            if course_code.startswith("GOSO-KZ-"):
                if jurisdiction_kz:
                    item["regulatory_required"] = True
                    item["admission_reason"] = "mandatory_goso_kz"
                    admitted.append(item)
                continue
            if not _education_level_course_allowed(course, constraints.get("education_level")):
                continue
            evidence = aggregates.get(course.id, {})
            # Generic GSOS outcomes justify only explicit GOSO courses.
            # An ordinary EPVO elective must support at least one programme-
            # specific professional outcome.
            credible_los = set(evidence.get("professional_lo_codes") or set())
            if not credible_los:
                continue
            if course_code.startswith("EPVO-") and scope_rank(course) <= 0:
                continue
            if (
                course_code.startswith("EPVO-")
                and not course_matches_scope_theme(course)
                and not has_strong_exact_scope_evidence(course)
            ):
                continue
            if not is_project_domain(course):
                continue
            item["admission_reason"] = (
                "epvo_scope_and_lo"
                if scope_rank(course) > 0 or course_code.startswith("EPVO-")
                else "local_course_and_lo"
            )
            item["admission_los"] = sorted(credible_los)
            item["admission_score"] = round(float(evidence.get("max") or 0.0), 4)
            admitted.append(item)
        return _unique_items_by_title(admitted)

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
    def rank(cid):
        data, course = aggregates[cid], courses.get(cid)
        credits = max(1, course.credits if course else 1)
        # EPVO's recommended semester is advisory, but using it as a stable
        # tie-breaker prevents a late specialised course from displacing an
        # equally evidenced foundation course.  Prerequisite repair remains
        # authoritative after selection.
        semester_preference = -int(course.recommended_semester or 99)
        if variant_type == "B":
            # Reuse-first variant: prefer scoped existing courses with a simple
            # prerequisite chain, but avoid overloading early semesters with
            # several large 8-9 credit foundations.
            return (
                role_rank(course),
                scope_rank(course),
                priority_rank(course),
                semester_stability_rank(course),
                semester_preference,
                -course_depth(cid),
                -len(prereq_ids_by_course.get(cid, [])),
                data["max"],
                -credits,
                course.id,
            )
        if variant_type == "C":
            domains = {(version.project.domain1 or "").lower(), (version.project.domain2 or "").lower()}
            domain_bonus = 1 if course and any(d and (d in (course.domain or "").lower() or (course.domain or "").lower() in d) for d in domains) else 0
            return (role_rank(course), scope_rank(course), priority_rank(course), semester_stability_rank(course), semester_preference, -len(prereq_ids_by_course.get(cid, [])), domain_bonus, data["sum"] / credits, -course_depth(cid), -course.id)
        return (role_rank(course), scope_rank(course), priority_rank(course), semester_stability_rank(course), semester_preference, len(data["los"]), data["sum"], data["max"], -course_depth(cid), -course.id)
    candidate_ids = sorted(
        (cid for cid in aggregates if cid in courses and is_project_domain(courses[cid]) and course_depth(cid) < num_semesters),
        key=rank,
        reverse=True,
    )
    # Seed data and imported catalogues may contain several rows for the same
    # discipline.  They are alternatives, not separate curriculum subjects.
    unique_candidate_ids = []
    seen_candidate_titles = set()
    for cid in candidate_ids:
        title = _title_key(courses[cid].title)
        if title in seen_candidate_titles:
            continue
        seen_candidate_titles.add(title)
        unique_candidate_ids.append(cid)
    # A large EPVO scope can contain many thousands of eligible rows.  The
    # deterministic scheduler only needs a ranked frontier; traversing the
    # complete catalogue makes each variant quadratic and can exhaust memory.
    # Keep enough diversity for both domains while bounding generation time.
    candidate_ids = unique_candidate_ids[:100]
    root_credits = sum(
        int(course.credits or 5)
        for course in courses.values()
        if is_project_domain(course) and course_depth(course.id) == 0
    )
    foundation_reserve = min(
        max(0, int(constraints.get("max_credits_per_semester", 30)) - root_credits),
        int(constraints.get("max_new_courses", 5)) * 7,
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
    def bundle(cid, visiting=None):
        visiting = visiting or set()
        if cid in visiting or cid in selected or cid not in courses: return []
        # A domain course can reference a generic prerequisite in the repository.
        # Do not silently pull that foreign-domain prerequisite into this project;
        # reject the whole bundle and let the bridge-module fallback close the gap.
        if not is_project_domain(courses[cid]):
            return []
        result = []
        for pre_id in prereq_ids_by_course.get(cid, []):
            prerequisite_bundle = bundle(pre_id, visiting | {cid})
            if pre_id not in selected and not prerequisite_bundle:
                return []
            result.extend(prerequisite_bundle)
        if cid not in selected and all(item["course_id"] != cid for item in result):
            c = courses[cid]; result.append({"course_id": c.id, "title": c.title, "domain": c.domain, "credits": c.credits or 5, "recommended_semester": c.recommended_semester, "prerequisites": prereq_ids_by_course.get(c.id, []), "type": c.cycle_component or "mandatory"})
        return result
    total = 0
    foundation_target = max(0, int(constraints.get("max_credits_per_semester", target / max(num_semesters, 1))) - 3)
    foundation_ids = sorted(
        (cid for cid in courses if is_project_domain(courses[cid]) and course_depth(cid) == 0),
        key=lambda cid: tuple(rank(cid)) if cid in aggregates else (0, 0, 0),
        reverse=True,
    )
    for cid in foundation_ids:
        foundation_bundle = bundle(cid)
        item = foundation_bundle[-1] if foundation_bundle else None
        if not item or total + item["credits"] > maximum: continue
        selected[cid] = item; total += item["credits"]
        if total >= foundation_target: break

    def selected_domain_credits(domain_index: int) -> int:
        value = 0
        for item in selected.values():
            course = courses.get(item.get("course_id"))
            if course and project_domain_index(course) == domain_index:
                value += int(item.get("credits") or 0)
        return value

    domain_quota_candidate_cache: Dict[int, List[Course]] = {}

    def domain_quota_candidates(domain_index: int) -> List[Course]:
        cached = domain_quota_candidate_cache.get(domain_index)
        if cached is not None:
            return cached
        cached = sorted(
            (
                course for course in courses.values()
                if is_project_domain(course)
                and project_domain_index(course) == domain_index
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
                index = project_domain_index(course) if course else None
                if index in (0, 1):
                    values[index] += int(item.get("credits") or 0)
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
            return prerequisite_ids | expert_confirmed_ids

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
                    normalized[replace_index] = {
                        "course_id": candidate.id,
                        "title": candidate.title,
                        "domain": candidate.domain,
                        "credits": candidate.credits or 5,
                        "recommended_semester": candidate.recommended_semester,
                        "prerequisites": prereq_ids_by_course.get(candidate.id, []),
                        "type": candidate.cycle_component or "mandatory",
                        "selection_method": "domain_quota_rebalance",
                    }
                    swapped = True
                    break
                if not swapped:
                    # Credit values in EPVO are heterogeneous (3/4/5). A
                    # strict one-for-one swap can stop below quota even when
                    # enough strong courses exist. Try bounded 1–2 course
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
                    for size in (1, 2):
                        for group in combinations(replaceable_all, size):
                            group_credits = sum(int(row[1].get("credits") or 0) for row in group)
                            other_domain = project_domain_index(group[0][2])
                            if (
                                other_domain not in (0, 1)
                                or current[other_domain] - group_credits >= required[other_domain]
                            ):
                                replacement_groups.setdefault(group_credits, []).append(group)
                    candidate_groups = [*( (course,) for course in candidates )]
                    candidate_groups.extend(combinations(candidates[:40], 2))
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
                    replaceable_all = replaceable_all[:24]
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

    def replace_redundant_bridges_with_real_courses(items: List[Dict], protected_bridge_ids: set[int] | None = None) -> List[Dict]:
        """Replace a bridge only when its LO role is already supported by real courses.

        This prevents historical/forced bridge modules from surviving after a
        later EPVO repository expansion has supplied suitable real courses.
        Credit equality keeps the plan envelope unchanged.
        """
        normalized = [dict(item) for item in items]
        protected_bridge_ids = protected_bridge_ids or set()
        bridge_ids = {
            int(item.get("bridge_module_id"))
            for item in normalized
            if item.get("bridge_module_id") is not None
        } - protected_bridge_ids
        if not bridge_ids:
            return normalized
        bridge_by_id = {
            bridge.id: bridge
            for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids)).all()
        }
        selected_real_ids = {
            int(item["course_id"])
            for item in normalized
            if item.get("course_id") is not None
        }
        covered_codes = set()
        for course_id in selected_real_ids:
            evidence = aggregates.get(course_id, {})
            if float(evidence.get("max") or 0.0) >= float(settings.COVERAGE_THRESHOLD):
                covered_codes.update(evidence.get("lo_codes") or set())

        candidates = [
            course for course in courses.values()
            if course.id not in selected_real_ids
            and is_project_domain(course)
            and scope_rank(course) >= 2
            and _course_curriculum_role(course, project_domains) != "general"
            and all(
                prerequisite_id in selected_real_ids
                for prerequisite_id in prereq_ids_by_course.get(course.id, [])
            )
            and float(aggregates.get(course.id, {}).get("max") or 0.0) >= 0.4
        ]
        used = set(selected_real_ids)
        for index, item in enumerate(normalized):
            bridge_id = item.get("bridge_module_id")
            if bridge_id is None or int(bridge_id) in protected_bridge_ids:
                continue
            bridge = bridge_by_id.get(int(bridge_id))
            if not bridge:
                continue
            target_codes = set(bridge.target_los or [])
            if target_codes and not target_codes.issubset(covered_codes):
                continue
            same_credit = [
                course for course in candidates
                if course.id not in used and int(course.credits or 5) == int(item.get("credits") or 5)
            ]
            if not same_credit:
                continue
            same_credit.sort(
                key=lambda course: (
                    len(set(aggregates.get(course.id, {}).get("lo_codes") or set()) & target_codes),
                    float(aggregates.get(course.id, {}).get("expert") or 0.0),
                    float(aggregates.get(course.id, {}).get("max") or 0.0),
                    priority_rank(course),
                ),
                reverse=True,
            )
            replacement = same_credit[0]
            used.add(replacement.id)
            normalized[index] = {
                "course_id": replacement.id,
                "title": replacement.title,
                "domain": replacement.domain,
                "credits": int(item.get("credits") or replacement.credits or 5),
                "recommended_semester": replacement.recommended_semester,
                "prerequisites": [],
                "type": replacement.cycle_component or "elective",
                "selection_method": "redundant_bridge_replaced_by_epvo",
            }
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
            if cid in courses and project_domain_index(courses[cid]) == domain_index
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
                selected[item["course_id"]] = item
            total = sum(item["credits"] for item in selected.values())

    # Respect the quotas entered in the project wizard before the generic fill.
    if interdisciplinary:
        fill_domain_quota(1)
    fill_domain_quota(0)

    for cid in candidate_ids:
        additions = list({item["course_id"]: item for item in bundle(cid) if item["course_id"] not in selected}.values())
        addition_credits = sum(item["credits"] for item in additions)
        if total + addition_credits > maximum: continue
        for item in additions: selected[item["course_id"]] = item
        total = sum(item["credits"] for item in selected.values())
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
        configured_max_new_courses = int(constraints.get("max_new_courses", 5))
        max_new_courses = max(configured_max_new_courses, existing_bridge_count + math.ceil(max(0, target - total) / 7))
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
    confirmed_course_replacements = {
        int(course_id): int(replacement_id)
        for course_id, replacement_id in (constraints.get("confirmed_course_replacements") or {}).items()
        if str(course_id).isdigit() and str(replacement_id).isdigit()
    }
    if confirmed_course_replacements:
        selected_ids = {int(item.get("course_id")) for item in result if item.get("course_id")}
        for index, item in enumerate(result):
            old_id = int(item.get("course_id") or 0)
            replacement_id = confirmed_course_replacements.get(old_id)
            replacement = courses.get(replacement_id)
            if not replacement or replacement_id in selected_ids:
                continue
            selected_ids.discard(old_id)
            selected_ids.add(replacement_id)
            result[index] = {
                "course_id": replacement.id,
                "title": replacement.title,
                "domain": replacement.domain,
                "credits": int(item.get("credits") or replacement.credits or 5),
                "recommended_semester": int(item.get("recommended_semester") or replacement.recommended_semester or 1),
                "latest_semester": int(item.get("latest_semester") or num_semesters),
                "prerequisites": prereq_ids_by_course.get(replacement.id, []),
                "type": replacement.cycle_component or item.get("type") or "elective",
                "selection_method": "expert_confirmed_course_replacement",
            }
    confirmed_replacements = {
        int(bridge_id): int(course_id)
        for bridge_id, course_id in (constraints.get("confirmed_bridge_replacements") or {}).items()
        if str(bridge_id).isdigit() and str(course_id).isdigit()
    }
    result = replace_redundant_bridges_with_real_courses(result, set(confirmed_replacements))
    result = rebalance_domain_quotas(result)
    if confirmed_replacements:
        for index, item in enumerate(result):
            course_id = confirmed_replacements.get(int(item.get("bridge_module_id") or 0))
            course = courses.get(course_id)
            if not course:
                continue
            result[index] = {
                "course_id": course.id,
                "title": course.title,
                "domain": course.domain,
                # Expert confirmation replaces the bridge content/name but
                # preserves the curriculum credit envelope and semester slot.
                "credits": int(item.get("credits") or course.credits or 5),
                "recommended_semester": int(item.get("recommended_semester") or course.recommended_semester or 1),
                "latest_semester": int(item.get("latest_semester") or num_semesters),
                "prerequisites": prereq_ids_by_course.get(course.id, []),
                "type": course.cycle_component or "mandatory",
                "selection_method": "expert_confirmed_ai_bridge_replacement",
            }
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
    result = replace_redundant_bridges_with_real_courses(result)
    result = _trim_to_target_credits(result, target, db)
    result = rebalance_domain_quotas(result)
    # The last trim/bridge replacement must not remove the sole real source
    # for a programme LO. Reclose gaps at the true end of selection.
    result = close_professional_lo_gaps(result)
    result = admit_real_courses(result)
    result = top_up_with_real_epvo_courses(result)
    result = top_up_with_credit_bridges(result)
    result = replace_redundant_bridges_with_real_courses(result)
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


def ensure_core_interdisciplinary_bridge(project_version: ProjectVersion, db: Session) -> BridgeModule | None:
    """Create one explicit domain-bridge module for interdisciplinary programmes."""
    project = project_version.project
    constraints = project.constraints_json or {}
    program_type = str(constraints.get("program_type") or "").lower()
    domain1, domain2 = (project.domain1 or "").strip(), (project.domain2 or "").strip()
    if program_type not in {"interdisciplinary", "joint"} or not domain1 or not domain2:
        return None
    if _title_key(domain1) == _title_key(domain2):
        return None

    total_semesters = int(constraints.get("total_semesters", 8) or 8)
    code = f"CORE_BRIDGE_{project_version.id}"
    domain1_display = "IT" if _title_key(domain1) in {"it", "айти"} else domain1
    domain2_key = _title_key(domain2)
    domain2_display = "медицина" if any(token in domain2_key for token in ("medicine", "medical", "медицин", "медицина", "health", "clinical", "клиник")) else domain2
    title = f"Интеграционный модуль: {domain1_display} и {domain2_display}"
    target_los = [
        lo.lo_code for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    ]
    module = db.query(BridgeModule).filter(
        BridgeModule.project_version_id == project_version.id,
        BridgeModule.course_id == code,
    ).first()
    payload = {
        "title": title,
        "goal": f"Связать {domain1} и {domain2} в прикладном междисциплинарном проекте.",
        "description": (
            f"Bridge-модуль для программы {project.title}: студенты применяют IT-инструменты, "
            f"данные и цифровые платформы к задачам области {domain2}, учитывая безопасность, "
            "этику, нормативные ограничения и доказательность решений."
        ),
        "credits": 5,
        "recommended_semester": max(2, min(total_semesters - 1, total_semesters // 2)),
        "learning_outcomes": [
            f"Применять цифровые инструменты и данные для решения задач области {domain2}.",
            f"Проектировать междисциплинарное решение на стыке {domain1} и {domain2}.",
            "Оценивать безопасность, этику, качество данных и нормативные ограничения решения.",
        ],
        "topics": [
            f"Проблемное поле {domain2} для IT-решений",
            "Медицинские/профессиональные данные и качество источников",
            "Цифровые платформы, интеграция и безопасность",
            "Этика, приватность и регуляторные ограничения",
            "Командный проект и защита решения",
        ],
        "assessment_methods": ["проект", "case study", "презентация"],
        "target_los": target_los,
    }
    if module is None:
        module = BridgeModule(
            project_version_id=project_version.id,
            course_id=code,
            prerequisites=[],
            source_chunks_json=[],
            generation_params_json={"mode": "core_interdisciplinary_bridge"},
            **payload,
        )
        db.add(module)
    else:
        for key, value in payload.items():
            setattr(module, key, value)
        module.prerequisites = []
        module.generation_params_json = {"mode": "core_interdisciplinary_bridge"}
    db.flush()
    return module


def ensure_secondary_domain_bridge_modules(project_version: ProjectVersion, db: Session) -> List[BridgeModule]:
    """Create visible secondary-domain modules for interdisciplinary curricula."""
    project = project_version.project
    constraints = project.constraints_json or {}
    program_type = str(constraints.get("program_type") or "").lower()
    domain1, domain2 = (project.domain1 or "").strip(), (project.domain2 or "").strip()
    if program_type not in {"interdisciplinary", "joint"} or not domain1 or not domain2:
        return []
    total_semesters = int(constraints.get("total_semesters", 8) or 8)
    secondary = domain2
    secondary_key = _title_key(secondary)
    is_medical = any(token in secondary_key for token in ("medicine", "medical", "медицин", "медицина", "health", "clinical", "клиник"))
    secondary_display = "медицины" if is_medical else secondary
    templates = [
        {
            "suffix": "SECONDARY_FOUNDATION",
            "title": f"Основы {secondary_display} для IT-специалистов" if is_medical else f"Основы области {secondary} для {domain1}",
            "semester": 2,
            "topics": [
                "Профессиональный контекст и терминология",
                "Типовые процессы и участники отрасли",
                "Данные, документы и доказательность",
                "Риски, этика и нормативные ограничения",
            ],
        },
        {
            "suffix": "SECONDARY_DATA",
            "title": "Медицинские данные и клинические процессы" if is_medical else f"Данные и процессы области {secondary}",
            "semester": 3,
            "topics": [
                "Структура профессиональных данных",
                "Качество, полнота и интерпретация данных",
                "Цифровой workflow и интеграция систем",
                "Прикладной кейс междисциплинарного анализа",
            ],
        },
        {
            "suffix": "SECONDARY_ADVANCED",
            "title": "Прикладной проект в области медицины" if is_medical else f"Прикладной проект области {secondary}",
            "semester": max(4, min(total_semesters - 1, 5)),
            "topics": [
                "Постановка междисциплинарной задачи",
                "Интерпретация отраслевых данных",
                "Оценка рисков и ограничений решения",
                "Защита прикладного проекта",
            ],
        },
    ]
    target_los = [
        lo.lo_code for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    ]
    modules: List[BridgeModule] = []
    for index, template in enumerate(templates, start=1):
        code = f"{template['suffix']}_{project_version.id}"
        module = db.query(BridgeModule).filter(
            BridgeModule.project_version_id == project_version.id,
            BridgeModule.course_id == code,
        ).first()
        payload = {
            "title": template["title"],
            "goal": f"Дать студентам {domain1} предметную базу области {secondary} для корректного проектирования цифровых решений.",
            "description": (
                f"Предметный модуль вторичного домена {secondary}: терминология, процессы, данные, "
                "ограничения и кейсы, необходимые для междисциплинарной образовательной программы."
            ),
            "credits": 3 if template["suffix"] == "SECONDARY_ADVANCED" else 5,
            "recommended_semester": max(1, min(total_semesters - 1, int(template["semester"]))),
            "learning_outcomes": [
                f"Объяснять ключевые процессы и понятия области {secondary}.",
                f"Интерпретировать данные области {secondary} для задач {domain1}.",
                "Учитывать этические, правовые и качественные ограничения предметной области.",
            ],
            "topics": template["topics"],
            "assessment_methods": ["case study", "практическое задание", "мини-проект"],
            "target_los": target_los[index - 1::2] or target_los,
        }
        if module is None:
            module = BridgeModule(
                project_version_id=project_version.id,
                course_id=code,
                prerequisites=[],
                source_chunks_json=[],
                generation_params_json={"mode": "secondary_domain_foundation"},
                **payload,
            )
            db.add(module)
        else:
            for key, value in payload.items():
                setattr(module, key, value)
            module.prerequisites = []
            module.generation_params_json = {"mode": "secondary_domain_foundation"}
        modules.append(module)
    db.flush()
    return modules


def ensure_credit_bridge_modules(
    project_version: ProjectVersion,
    db: Session,
    needed_credits: int,
    slots: int,
    desired_count: int | None = None,
) -> List[BridgeModule]:
    """Create deterministic domain-aware bridge modules when constraints leave credit gaps.

    This avoids filling a curriculum with unrelated repository courses simply
    because they have no prerequisites. The modules remain explicit bridge
    candidates and can later be promoted by an expert.
    """
    if needed_credits <= 0 or slots <= 0:
        return []

    project = project_version.project
    # Regulatory ГОСО outcomes are already evidenced by the mandatory
    # components merged into every KZ curriculum.  A synthetic credit-gap
    # module must never claim those outcomes: doing so both overstates its
    # pedagogical role and prevents the final EPVO replacement pass from
    # recognising the bridge as redundant.
    learning_outcomes = [
        lo for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    ]
    lo_codes = [lo.lo_code for lo in learning_outcomes]
    lo_by_code = {lo.lo_code: lo for lo in learning_outcomes}
    base_code = f"AUTO_BRIDGE_{project_version.id}_"
    existing = {
        bm.course_id: bm
        for bm in db.query(BridgeModule).filter(
            BridgeModule.project_version_id == project_version.id,
            BridgeModule.course_id.like(f"{base_code}%"),
        ).all()
    }

    remaining = int(needed_credits)
    modules: List[BridgeModule] = []
    minimum_count = max(1, math.ceil(remaining / 7))
    maximum_count = max(1, min(slots, remaining // 3))
    count = min(maximum_count, max(minimum_count, desired_count or minimum_count))
    for index in range(1, count + 1):
        module_code = f"{base_code}{index}"
        slots_left = count - index + 1
        credits = max(3, min(7, math.ceil(remaining / slots_left)))
        remaining -= credits
        target_los = lo_codes[index - 1::count] or lo_codes
        theme = _short_lo_theme(lo_by_code.get(target_los[0]) if target_los else None)
        domain_pair = (
            f"{project.domain1} и {project.domain2}"
            if project.domain1 and project.domain2 and project.domain1 != project.domain2
            else str(project.domain1 or project.domain2 or "выбранного направления")
        )
        title = f"Интеграционный модуль {theme}: {domain_pair} - семестр {index}"
        goal = f"Закрыть разрыв по {', '.join(target_los[:3]) or 'результатам обучения'} через практическую связь направлений {domain_pair}."
        description = (
            f"Bridge-модуль связывает дисциплины направления {domain_pair} с результатами "
            f"{', '.join(target_los[:4]) or 'обучения программы'}. Используется только когда "
            "в репозитории ЕПВО пока нет достаточно сильной реальной дисциплины."
        )
        bm = existing.get(module_code)
        if bm is None:
            bm = BridgeModule(
                project_version_id=project_version.id,
                course_id=module_code,
                title=title,
                goal=goal,
                description=description,
                credits=credits,
                recommended_semester=min(index, int((project.constraints_json or {}).get("total_semesters", 1))),
                learning_outcomes=[
                    f"Apply {project.domain2} tools to professional tasks in {project.domain1}.",
                    "Evaluate data, platform, legal, ethical, and cybersecurity constraints.",
                    "Design evidence-based digital transformation recommendations.",
                ],
                topics=[
                    "Digital transformation context",
                    "Data-driven public administration",
                    "GovTech platforms and interoperability",
                    "Information security and personal data protection",
                    "AI-supported decision-making",
                    "Implementation roadmap and stakeholder communication",
                ],
                prerequisites=[],
                assessment_methods=["project", "case study", "presentation"],
                source_chunks_json=[],
                generation_params_json={"mode": "deterministic_credit_gap_bridge"},
                target_los=target_los,
            )
            db.add(bm)
        else:
            bm.credits = credits
            bm.title = title
            bm.goal = goal
            bm.description = description
            bm.target_los = target_los
        modules.append(bm)

    db.flush()
    return modules
