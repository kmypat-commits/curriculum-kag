from __future__ import annotations

from itertools import combinations
import re
from statistics import median
from typing import Dict, List

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.bridge_module import BridgeModule
from app.models.course import Course, course_prerequisites
from app.models.embedding import MatchScore
from app.models.epvo import EpvoDisciplineNormalized
from app.models.project import ProjectVersion
from app.planner.admission import (
    audit_final_course_admission as _audit_final_course_admission,
    credible_professional_lo_by_course as _credible_professional_lo_by_course,
    minimum_appropriate_semester as _minimum_appropriate_semester,
)
from app.planner.course_policy import (
    education_level_course_allowed as _education_level_course_allowed,
    project_domain_terms as _project_domain_terms,
)
from app.planner.scheduler_catalogue import unique_items_by_title as _unique_items_by_title
from app.planner.domain_evidence import domain_credit_shares
from app.planner.scheduler_domain_rules import (
    has_foreign_professional_title as _has_foreign_professional_title,
    is_it_medicine_support_course as _is_it_medicine_support_course,
)
from app.planner.scheduler_utils import (
    move_item as _move_item,
    swap_items as _swap_items,
    title_key as _title_key,
)
from app.planner.semester_rules import (
    complexity_min_semester as _complexity_min_semester,
    foundation_max_semester as _foundation_max_semester,
    late_stage_min_semester as _late_stage_min_semester,
    minimum_appropriate_semester as _item_minimum_appropriate_semester,
)
from app.planner.verifier import verify_curriculum_plan
from app.services.epvo_repository import epvo_row_matches_education_level
from app.planner.scoped_epvo_semesters import apply_scoped_epvo_semesters as _apply_scoped_epvo_semesters


def _repair_semester_appropriateness(
    schedule: Dict[int, List[Dict]],
    num_semesters: int,
    nominal_load: int,
    db: Session,
) -> Dict[int, List[Dict]]:
    """Repair semantic semester bounds without breaking load/prerequisites."""
    course_ids = {
        int(item["course_id"])
        for items in schedule.values()
        for item in items
        if item.get("course_id") is not None
    }
    courses = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()
    }
    lower_load, upper_load = nominal_load - 3, nominal_load + 3

    def bounds(item: Dict) -> tuple[int, int]:
        if item.get("regulatory_required"):
            semester = max(1, min(num_semesters, int(item.get("recommended_semester") or 1)))
            return semester, semester
        course = courses.get(item.get("course_id"))
        if not course:
            return 1, num_semesters
        recommended = int(item.get("recommended_semester") or course.recommended_semester or 0)
        semantic_upper = _foundation_max_semester(course.title, num_semesters)
        if item.get("prerequisites"):
            # "Основы" can name a domain foundation built on earlier general
            # prerequisites (for example engineering calculations after
            # mathematics).  In that case the source semester and graph are
            # stronger evidence than the lexical prefix alone. A late source
            # recommendation by itself is not enough: EPVO often contains the
            # same introductory course in different programme semesters.
            semantic_upper = max(semantic_upper, min(num_semesters, recommended + 2))
        recommended_lower = max(1, recommended - 1) if recommended else 1
        # A late semester copied from one source programme must not turn an
        # explicitly introductory course into a capstone. Semantic foundation
        # bounds are authoritative when the two signals conflict.
        if recommended_lower > semantic_upper:
            recommended_lower = 1
        lower = max(
            1,
            _late_stage_min_semester(course.title, num_semesters),
            _complexity_min_semester({
                "title": course.title,
                "domain": item.get("domain") or course.domain,
                "type": item.get("type") or course.cycle_component,
            }, num_semesters),
            recommended_lower,
        )
        upper = max(lower, semantic_upper)
        return lower, min(num_semesters, upper)

    def prerequisites_valid(candidate: Dict[int, List[Dict]]) -> bool:
        semester_by_course = {
            item.get("course_id"): semester
            for semester, items in candidate.items()
            for item in items
            if item.get("course_id") is not None
        }
        return all(
            semester_by_course.get(prerequisite_id, 0) < semester
            for semester, items in candidate.items()
            for item in items
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in semester_by_course
        )

    for _ in range(2):
        changed = False
        loads = {
            semester: sum(int(item.get("credits") or 0) for item in items)
            for semester, items in schedule.items()
        }
        misplaced = [
            (semester, item, *bounds(item))
            for semester, items in schedule.items()
            for item in list(items)
            if item.get("course_id") is not None
            and not (bounds(item)[0] <= semester <= bounds(item)[1])
        ]
        for current, item, lower, upper in misplaced:
            credits = int(item.get("credits") or 0)
            targets = sorted(
                range(lower, upper + 1),
                key=lambda semester: (abs(semester - current), loads.get(semester, 0)),
            )
            repaired = False
            for target in targets:
                if target == current:
                    continue
                if (
                    loads[current] - credits >= lower_load
                    and loads[target] + credits <= upper_load
                ):
                    candidate = {semester: list(items) for semester, items in schedule.items()}
                    if not _move_item(candidate, current, target, item):
                        continue
                    if prerequisites_valid(candidate):
                        schedule = candidate
                        loads[current] -= credits
                        loads[target] += credits
                        repaired = changed = True
                        break
                for other in list(schedule[target]):
                    if other.get("course_id") is None:
                        continue
                    other_credits = int(other.get("credits") or 0)
                    new_current_load = loads[current] - credits + other_credits
                    new_target_load = loads[target] - other_credits + credits
                    if not (
                        lower_load <= new_current_load <= upper_load
                        and lower_load <= new_target_load <= upper_load
                    ):
                        continue
                    other_lower, other_upper = bounds(other)
                    if not (other_lower <= current <= other_upper):
                        continue
                    candidate = {semester: list(items) for semester, items in schedule.items()}
                    if not _swap_items(candidate, current, item, target, other):
                        continue
                    if prerequisites_valid(candidate):
                        schedule = candidate
                        loads[current] = new_current_load
                        loads[target] = new_target_load
                        repaired = changed = True
                        break
                if repaired:
                    break
            if repaired:
                continue
            # If the target semester has room but the current semester would
            # become underloaded, use one admissible foundation course from a
            # third semester to refill it.  This is a two-hop rotation:
            # ``late course -> valid target`` and ``flexible foundation ->
            # vacated current semester``.  It is necessary for 240-credit
            # programmes where every semester must remain inside 27--33 and
            # a direct 4-credit move would otherwise be rejected despite a
            # valid global timetable existing.
            for target in targets:
                if target == current or loads[target] + credits > upper_load:
                    continue
                for donor in sorted(
                    (value for value in schedule if value not in {current, target}),
                    key=lambda value: loads[value],
                    reverse=True,
                ):
                    for filler in list(schedule[donor]):
                        if (
                            filler.get("course_id") is None
                            or filler.get("regulatory_required")
                        ):
                            continue
                        filler_credits = int(filler.get("credits") or 0)
                        filler_lower, filler_upper = bounds(filler)
                        if not (filler_lower <= current <= filler_upper):
                            continue
                        candidate_loads = {
                            current: loads[current] - credits + filler_credits,
                            target: loads[target] + credits,
                            donor: loads[donor] - filler_credits,
                        }
                        if any(
                            not lower_load <= candidate_loads[value] <= upper_load
                            for value in candidate_loads
                        ):
                            continue
                        candidate = {
                            value: list(items) for value, items in schedule.items()
                        }
                        if not _move_item(candidate, current, target, item):
                            continue
                        if not _move_item(candidate, donor, current, filler):
                            continue
                        if not prerequisites_valid(candidate):
                            continue
                        schedule = candidate
                        loads.update(candidate_loads)
                        repaired = changed = True
                        break
                    if repaired:
                        break
                if repaired:
                    break
        if not changed:
            break

    # A one-for-one swap is sometimes impossible when every early semester is
    # full of 3-credit courses while the misplaced foundation has 5 credits.
    # Try a bounded three-way rotation (late -> early -> middle -> late).  This
    # preserves semester loads, semantic bounds and every prerequisite edge.
    for _ in range(3):
        loads = {
            semester: sum(int(item.get("credits") or 0) for item in items)
            for semester, items in schedule.items()
        }
        unresolved = [
            (semester, item, *bounds(item))
            for semester, items in schedule.items()
            for item in list(items)
            if item.get("course_id") is not None
            and not (bounds(item)[0] <= semester <= bounds(item)[1])
        ]
        rotated = False
        for current, item, lower, upper in unresolved:
            item_credits = int(item.get("credits") or 0)
            for target in range(lower, upper + 1):
                if target == current:
                    continue
                for displaced in list(schedule[target]):
                    if displaced.get("regulatory_required") or displaced.get("course_id") is None:
                        continue
                    displaced_credits = int(displaced.get("credits") or 0)
                    for receiver in schedule:
                        if receiver in {current, target}:
                            continue
                        displaced_lower, displaced_upper = bounds(displaced)
                        if not (displaced_lower <= receiver <= displaced_upper):
                            continue
                        for third in list(schedule[receiver]):
                            if third.get("regulatory_required") or third.get("course_id") is None:
                                continue
                            third_lower, third_upper = bounds(third)
                            if not (third_lower <= current <= third_upper):
                                continue
                            third_credits = int(third.get("credits") or 0)
                            candidate_loads = {
                                **loads,
                                current: loads[current] - item_credits + third_credits,
                                target: loads[target] - displaced_credits + item_credits,
                                receiver: loads[receiver] - third_credits + displaced_credits,
                            }
                            if any(
                                not lower_load <= candidate_loads[semester] <= upper_load
                                for semester in (current, target, receiver)
                            ):
                                continue
                            candidate = {semester: list(items) for semester, items in schedule.items()}
                            if not _move_item(candidate, current, target, item):
                                continue
                            if not _move_item(candidate, target, receiver, displaced):
                                continue
                            if not _move_item(candidate, receiver, current, third):
                                continue
                            if not prerequisites_valid(candidate):
                                continue
                            schedule = candidate
                            rotated = True
                            break
                        if rotated:
                            break
                    if rotated:
                        break
                if rotated:
                    break
            if rotated:
                break
        if not rotated:
            break
    return schedule
