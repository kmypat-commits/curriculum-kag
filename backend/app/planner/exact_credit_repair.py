"""Bounded, evidence-preserving exact-credit repair for final timetables."""

from __future__ import annotations

from itertools import combinations
from typing import Callable

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.models.course import Course
from app.models.epvo import EpvoDisciplineNormalized
from app.models.embedding import MatchScore
from app.models.project import ProjectVersion
from app.planner.admission import audit_final_course_admission, credible_professional_lo_by_course
from app.planner.course_policy import education_level_course_allowed
from app.planner.epvo_course_links import epvo_code_index, linked_course_id
from app.planner.match_aggregation import semantic_evidence_score
from app.planner.scheduler_utils import title_key
from app.planner.verifier import _ict_competency_audit, verify_curriculum_plan
from app.services.epvo_repository import epvo_row_matches_education_level


def repair_exact_real_credit_overage(
    schedule: dict[int, list[dict]],
    project_version: ProjectVersion,
    db: Session,
    *,
    is_admissible: Callable[[Course], bool] | None = None,
    variant_type: str = "A",
) -> dict[int, list[dict]]:
    """Replace at most two real courses; never rewrite repository credits.

    Late regulatory/competency reconstruction can leave a 1--3 credit excess
    that no whole-course deletion can resolve. Search only scoped, level-valid
    EPVO courses with credible professional-LO evidence. Every proposed
    timetable must pass the independent verifier and final admission audit.
    If no such plan exists, return the original schedule unchanged.
    """
    constraints = project_version.project.constraints_json or {}
    target = int(constraints.get("total_credits") or 0)
    total = sum(int(item.get("credits") or 0) for rows in schedule.values() for item in rows)
    excess = total - target
    if excess not in (1, 2, 3):
        return schedule

    selected_ids = {
        int(item["course_id"])
        for rows in schedule.values() for item in rows
        if item.get("course_id") is not None
    }
    protected_ids = {
        int(parent)
        for rows in schedule.values() for item in rows
        for parent in item.get("prerequisites") or []
        if int(parent) in selected_ids
    }
    slots = [
        (semester, index, item)
        for semester, rows in schedule.items() for index, item in enumerate(rows)
        if item.get("course_id") is not None
        and not item.get("regulatory_required")
        and int(item["course_id"]) not in protected_ids
        and int(item.get("credits") or 0) > 1
    ]
    if not slots:
        return schedule

    lo_codes = {
        lo.id: str(lo.lo_code or "") for lo in project_version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    }
    evidence_scores: dict[int, float] = {}
    for match in db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version.id,
        MatchScore.lo_id.in_(set(lo_codes) or {-1}),
    ).all():
        expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        score = max(semantic_evidence_score(match), expert)
        if score >= 0.4:
            course_id = int(match.course_id)
            evidence_scores[course_id] = max(evidence_scores.get(course_id, 0.0), score)
    candidate_ids = set(evidence_scores) - selected_ids
    if not candidate_ids:
        return schedule
    courses = {
        course.id: course for course in db.query(Course)
        .options(selectinload(Course.prerequisites))
        .filter(Course.id.in_(candidate_ids)).all()
    }
    epvo_index = epvo_code_index(courses)
    scope_pairs = [
        (str(constraints.get("group_code") or ""), str(constraints.get("direction_code") or "")),
    ]
    if str(constraints.get("program_type") or "").lower() in {"interdisciplinary", "joint"}:
        scope_pairs.append((
            str(constraints.get("secondary_group_code") or ""),
            str(constraints.get("secondary_direction_code") or ""),
        ))
    scoped_ids: set[int] = set()
    for row in db.query(EpvoDisciplineNormalized).filter(or_(
        EpvoDisciplineNormalized.approved_course_id.in_(candidate_ids),
        EpvoDisciplineNormalized.id.in_(set(epvo_index) or {-1}),
    )).all():
        if not epvo_row_matches_education_level(row, constraints.get("education_level")):
            continue
        groups = {str(value or "") for value in row.group_codes or []}
        directions = {str(value or "") for value in row.direction_codes or []}
        if any(
            (group and group in groups) or (direction and direction in directions)
            for group, direction in scope_pairs
        ):
            course_id = linked_course_id(row, epvo_index)
            if course_id is not None:
                scoped_ids.add(int(course_id))
    credible = credible_professional_lo_by_course(project_version, candidate_ids, db)
    selected_titles = {
        title_key(item.get("title"))
        for rows in schedule.values() for item in rows
        if item.get("title")
    }
    candidates = [
        course for course_id, course in courses.items()
        if course_id in scoped_ids
        and course_id in credible
        and education_level_course_allowed(course, constraints.get("education_level"))
        and (is_admissible is None or is_admissible(course))
        and title_key(course.title) not in selected_titles
    ]
    candidates.sort(key=lambda course: (-evidence_scores[course.id], course.id))

    # Each option reduces the total by a known positive amount. The small
    # frontier is deterministic; title/competency/prerequisite checks below
    # discard misleading high-scoring lexical matches before verification.
    options: list[tuple[int, int, dict, Course, int]] = []
    for semester, index, old_item in slots:
        old_credits = int(old_item["credits"])
        for course in candidates:
            reduction = old_credits - int(course.credits or 0)
            if not 1 <= reduction <= excess:
                continue
            parents = {parent.id for parent in course.prerequisites}
            if not parents.issubset(selected_ids - {int(old_item["course_id"])}):
                continue
            options.append((semester, index, old_item, course, reduction))

    def replacement(item: dict, course: Course) -> dict:
        return {
            **item,
            "course_id": course.id,
            "bridge_module_id": None,
            "title": course.title,
            "domain": course.domain,
            "credits": int(course.credits or 0),
            "recommended_semester": course.recommended_semester,
            "prerequisites": [parent.id for parent in course.prerequisites],
            "type": course.cycle_component or "elective",
            "selection_method": "exact_real_credit_repair",
            "admission_reason": "epvo_scope_and_lo",
            "admission_los": sorted(credible.get(course.id, set())),
            "admission_score": round(evidence_scores[course.id], 4),
        }

    def validated(options_to_apply: tuple) -> dict[int, list[dict]] | None:
        trial = {semester: [dict(item) for item in rows] for semester, rows in schedule.items()}
        chosen_ids = {option[3].id for option in options_to_apply}
        if len(chosen_ids) != len(options_to_apply):
            return None
        chosen_titles = {title_key(option[3].title) for option in options_to_apply}
        if len(chosen_titles) != len(options_to_apply):
            return None
        for semester, index, old_item, course, _reduction in options_to_apply:
            trial[semester][index] = replacement(old_item, course)
        selected_after = {
            int(item["course_id"])
            for rows in trial.values() for item in rows
            if item.get("course_id") is not None
        }
        if any(
            int(parent) not in selected_after
            for rows in trial.values() for item in rows
            for parent in item.get("prerequisites") or []
        ):
            return None
        if sum(int(item.get("credits") or 0) for rows in trial.values() for item in rows) != target:
            return None
        selected_courses = [
            db.get(Course, course_id) for course_id in selected_after
        ]
        if not _ict_competency_audit(
            [course for course in selected_courses if course is not None], constraints
        )["passed"]:
            return None
        admission = audit_final_course_admission(trial, project_version, db)
        if not admission["passed"]:
            return None
        verified = verify_curriculum_plan(trial, project_version, db)
        if verified.get("hard_violation_count") != 0 or verified.get("quality_passed") is not True:
            return None
        if str(constraints.get("jurisdiction") or "INTERNATIONAL").upper() == "KZ":
            if (verified.get("goso_compliance") or {}).get("compliant") is not True:
                return None
        return trial

    # One replacement is preferable to two; keep at most a bounded number
    # of equal-reduction options per slot before trying combinations.
    requested_rank = {"A": 1, "B": 2, "C": 3}.get(variant_type, 1)
    valid_seen = 0
    first_valid = None
    for option in options:
        if option[4] == excess:
            trial = validated((option,))
            if trial is not None:
                first_valid = first_valid or trial
                valid_seen += 1
                if valid_seen >= requested_rank:
                    return trial
    by_slot: dict[tuple[int, int], list[tuple]] = {}
    for option in options:
        key = (option[0], option[1])
        if len(by_slot.setdefault(key, [])) < 24:
            by_slot[key].append(option)
    bounded = [option for group in by_slot.values() for option in group]
    for left, right in combinations(bounded, 2):
        if (left[0], left[1]) == (right[0], right[1]):
            continue
        if left[4] + right[4] != excess:
            continue
        trial = validated((left, right))
        if trial is not None:
            first_valid = first_valid or trial
            valid_seen += 1
            if valid_seen >= requested_rank:
                return trial
    return first_valid or schedule
