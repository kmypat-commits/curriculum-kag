"""Course placement and semester scheduling.

This module owns deterministic course-to-semester placement; repair policy
remains in semester_repair.py.
"""
from __future__ import annotations

from statistics import median
from typing import Dict, List

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.bridge_module import BridgeModule
from app.models.course import Course
from app.models.epvo import EpvoDisciplineNormalized
from app.planner.scheduler_catalogue import unique_items_by_title as _unique_items_by_title
from app.planner.scheduler_utils import move_item as _move_item
from app.planner.semester_rules import (
    foundation_max_semester as _foundation_max_semester,
    late_stage_min_semester as _late_stage_min_semester,
    minimum_appropriate_semester as _item_minimum_appropriate_semester,
)

def schedule_courses(courses: List[Dict], num_semesters: int, nominal_load: int, db: Session) -> Dict[int, List[Dict]]:
    courses = _unique_items_by_title(courses)
    # EPVO may contain several historical rows for one canonical course.  A
    # single row's recommended semester is therefore unstable.  Before
    # placement, use the median of available EPVO semesters for each real
    # course.  Regulatory GOSO and bridge items keep their explicit semester.
    local_course_ids = {
        int(item["course_id"])
        for item in courses
        if item.get("course_id") is not None
        and not item.get("regulatory_required")
        and item.get("bridge_module_id") is None
    }
    local_to_epvo: Dict[int, int] = {}
    if local_course_ids:
        for course in db.query(Course).filter(Course.id.in_(local_course_ids)).all():
            code = str(course.course_id or "")
            if code.startswith("EPVO-"):
                try:
                    local_to_epvo[int(course.id)] = int(code.split("-", 1)[1])
                except (TypeError, ValueError):
                    continue
    epvo_course_ids = set(local_to_epvo.values())
    semester_values: Dict[int, List[int]] = {}
    if epvo_course_ids:
        rows = db.query(EpvoDisciplineNormalized).filter(
            or_(
                EpvoDisciplineNormalized.id.in_(epvo_course_ids),
                EpvoDisciplineNormalized.approved_course_id.in_(epvo_course_ids),
            )
        ).all()
        for row in rows:
            value = int(row.typical_semester or 0)
            if 1 <= value <= num_semesters:
                key = int(row.id) if int(row.id) in epvo_course_ids else int(row.approved_course_id)
                semester_values.setdefault(key, []).append(value)
    for item in courses:
        course_id = item.get("course_id")
        local_id = int(course_id) if course_id is not None else None
        epvo_id = local_to_epvo.get(local_id, local_id) if local_id is not None else None
        values = semester_values.get(epvo_id, []) if epvo_id is not None else []
        if values and not item.get("_scoped_epvo_semester"):
            item["recommended_semester"] = int(round(median(values)))
    schedule = {semester: [] for semester in range(1, num_semesters + 1)}
    loads = {semester: 0 for semester in schedule}
    lower, upper = max(0, nominal_load - 3), nominal_load + 3
    course_map = {item.get("course_id"): item for item in courses if item.get("course_id") is not None}
    depth_cache = {}
    def depth(cid, path=None):
        if cid in depth_cache: return depth_cache[cid]
        path = path or set()
        if cid in path: return num_semesters
        item = course_map.get(cid)
        if not item: return 0
        parents = [pid for pid in item.get("prerequisites", []) if pid in course_map]
        value = 0 if not parents else 1 + max(depth(pid, path | {cid}) for pid in parents)
        depth_cache[cid] = value; return value
    required_ids = {prerequisite for item in courses for prerequisite in (item.get("prerequisites", []) or [])}
    dependents = {}
    for item in courses:
        for prerequisite in item.get("prerequisites", []) or []:
            if prerequisite in course_map:
                dependents.setdefault(prerequisite, []).append(item.get("course_id"))
    tail_cache = {}
    def tail_depth(cid, path=None):
        if cid in tail_cache: return tail_cache[cid]
        path = path or set()
        if cid in path: return 0
        children = [child for child in dependents.get(cid, []) if child in course_map]
        value = 0 if not children else 1 + max(tail_depth(child, path | {cid}) for child in children)
        tail_cache[cid] = value
        return value
    ordered = sorted(courses, key=lambda item: (depth(item.get("course_id")) if item.get("course_id") else 0, 0 if item.get("course_id") in required_ids else 1, -(item.get("credits") or 0)))
    placed = {}
    for item in ordered:
        prereq_semesters = [placed[p] for p in item.get("prerequisites", []) if p in placed]
        earliest = min(max(prereq_semesters, default=0) + 1, num_semesters)
        regulatory_semester = (
            int(item.get("recommended_semester") or 1)
            if item.get("regulatory_required") and str(item.get("type") or "").startswith("goso_")
            else _late_stage_min_semester(item.get("title"), num_semesters)
        )
        earliest = max(earliest, min(num_semesters, regulatory_semester))
        # Keep initial placement and the independent final admission gate on
        # exactly the same lower-bound rule.  Previously the scheduler used
        # only lexical complexity here and could place a source-semester-8
        # professional course in semester 6; the final gate then had to
        # reject an otherwise valid plan after expensive scoring.
        earliest = max(
            earliest,
            _item_minimum_appropriate_semester(item, num_semesters),
        )
        recommended = item.get("variant_preferred_semester") or item.get("recommended_semester")
        semantic_upper = _foundation_max_semester(item.get("title"), num_semesters)
        if item.get("prerequisites") and recommended:
            semantic_upper = max(
                semantic_upper, min(num_semesters, int(recommended) + 2)
            )
        recommended_lower = max(1, int(recommended) - 1) if recommended else 1
        if recommended_lower <= semantic_upper:
            earliest = max(earliest, recommended_lower)
        cid = item.get("course_id")
        bridge_id = item.get("bridge_module_id")
        if bridge_id is not None:
            bridge = db.query(BridgeModule).filter(BridgeModule.id == bridge_id).first()
            if bridge and (bridge.course_id or "").startswith(("CORE_BRIDGE_", "SECONDARY_")):
                recommended_bridge_semester = int(bridge.recommended_semester or item.get("recommended_semester") or 1)
                item["recommended_semester"] = recommended_bridge_semester
                item["latest_semester"] = min(
                    num_semesters,
                    recommended_bridge_semester
                    + (2 if (bridge.course_id or "").startswith("CORE_BRIDGE_") else 1),
                )
        latest = max(earliest, min(
            int(item.get("latest_semester") or num_semesters),
            semantic_upper,
            num_semesters - (tail_depth(cid) if cid is not None else 0),
        ))
        item["latest_semester"] = latest
        candidates = list(range(earliest, latest + 1))
        valid = [s for s in candidates if loads[s] + (item.get("credits") or 0) <= upper]
        pool = valid or candidates
        target = min(
            pool,
            key=lambda semester: (
                abs(semester - int(recommended)) if recommended else 0,
                semester,
            ),
        )
        schedule[target].append(item); loads[target] += item.get("credits") or 0
        if item.get("course_id") is not None: placed[item["course_id"]] = target
    changed = True
    while changed:
        changed = False
        semester_by_course = {item["course_id"]: semester for semester, items in schedule.items() for item in items if item.get("course_id") is not None}
        for target_semester in [s for s in schedule if loads[s] < lower]:
            for donor_semester in sorted(schedule, key=lambda s: loads[s], reverse=True):
                if donor_semester == target_semester: continue
                for item in list(schedule[donor_semester]):
                    credits = item.get("credits") or 0
                    # Do not use a scoped EPVO course as a generic load
                    # shuttle: moving it away from its evidence-backed
                    # semester is exactly the failure measured by the
                    # external alignment audit.  Unscoped and bridge items
                    # remain available for balancing below.
                    if item.get("_scoped_epvo_semester") and item.get("source_semester_required"):
                        recommended_semester = int(item.get("recommended_semester") or 0)
                        if recommended_semester and target_semester != recommended_semester:
                            continue
                    if item.get("regulatory_required") and target_semester != int(item.get("recommended_semester") or donor_semester):
                        # Р“РћРЎРћ fixes the component and credit volume, but a
                        # practice can move one semester forward when this is
                        # the only way to keep the doctoral workload within
                        # the allowed band. Research stages and final defence
                        # remain locked to their normative semester.
                        flexible_practice = str(item.get("type") or "") in {
                            "goso_bd_practice", "goso_pd_practice",
                        }
                        recommended = int(item.get("recommended_semester") or donor_semester)
                        if not flexible_practice or target_semester != recommended + 1:
                            continue
                    if target_semester < _item_minimum_appropriate_semester(
                        item, num_semesters
                    ):
                        continue
                    if loads[donor_semester] - credits < lower or loads[target_semester] + credits > upper: continue
                    parent_semesters = [semester_by_course.get(p, 0) for p in item.get("prerequisites", []) or []]
                    child_semesters = [semester_by_course.get(d, num_semesters + 1) for d in dependents.get(item.get("course_id"), [])]
                    if parent_semesters and max(parent_semesters) >= target_semester: continue
                    if child_semesters and min(child_semesters) <= target_semester: continue
                    if not _move_item(schedule, donor_semester, target_semester, item):
                        continue
                    loads[donor_semester] -= credits; loads[target_semester] += credits
                    changed = True; break
                if changed: break
            if changed: break
    # A balanced load can still contain an avoidable semester inversion: an
    # EPVO-scoped course recommended for an early term may sit late while a
    # later course occupies its slot. Repair this with bounded-credit swaps so
    # loads remain within the configured tolerance. Every proposed swap is checked against both
    # prerequisite and dependent edges as well as semantic semester bounds.
    def improve_scoped_semester_alignment() -> None:
        def semester_map() -> Dict[int, int]:
            return {
                int(row.get("course_id")): int(semester)
                for semester, rows in schedule.items()
                for row in rows
                if row.get("course_id") is not None
            }

        def valid_assignment(item: Dict, target: int, mapping: Dict[int, int]) -> bool:
            if target < _item_minimum_appropriate_semester(item, num_semesters):
                return False
            latest = int(item.get("latest_semester") or num_semesters)
            if target > min(num_semesters, latest):
                return False
            course_id = item.get("course_id")
            if course_id is None:
                return True
            parents = [mapping.get(int(pid)) for pid in item.get("prerequisites", []) or []]
            if any(value is not None and value >= target for value in parents):
                return False
            children = [mapping.get(int(cid)) for cid in dependents.get(course_id, [])]
            if any(value is not None and value <= target for value in children):
                return False
            return True

        for _ in range(4):
            mapping = semester_map()
            best = None
            for left in range(1, num_semesters + 1):
                for left_item in schedule[left]:
                    if (
                        left_item.get("course_id") is None
                        or left_item.get("regulatory_required")
                    ):
                        continue
                    left_scoped = bool(left_item.get("_scoped_epvo_semester") and left_item.get("recommended_semester"))
                    left_credits = int(left_item.get("credits") or 0)
                    for right in range(left + 1, num_semesters + 1):
                        for right_item in schedule[right]:
                            if (
                                right_item.get("course_id") is None
                                or right_item.get("regulatory_required")
                            ):
                                continue
                            right_scoped = bool(right_item.get("_scoped_epvo_semester") and right_item.get("recommended_semester"))
                            if not left_scoped and not right_scoped:
                                continue
                            left_rec = int(left_item["recommended_semester"]) if left_scoped else None
                            right_rec = int(right_item["recommended_semester"]) if right_scoped else None
                            right_credits = int(right_item.get("credits") or 0)
                            if (
                                loads[left] - left_credits + right_credits < lower
                                or loads[left] - left_credits + right_credits > upper
                                or loads[right] - right_credits + left_credits < lower
                                or loads[right] - right_credits + left_credits > upper
                            ):
                                continue
                            before = (abs(left - left_rec) if left_rec is not None else 0) + (abs(right - right_rec) if right_rec is not None else 0)
                            after = (abs(right - left_rec) if left_rec is not None else 0) + (abs(left - right_rec) if right_rec is not None else 0)
                            if after >= before:
                                continue
                            trial = dict(mapping)
                            trial[int(left_item["course_id"])] = right
                            trial[int(right_item["course_id"])] = left
                            if not valid_assignment(left_item, right, trial):
                                continue
                            if not valid_assignment(right_item, left, trial):
                                continue
                            gain = before - after
                            if best is None or gain > best[0]:
                                best = (gain, left, left_item, right, right_item)
            if best is None:
                break
            _, left, left_item, right, right_item = best
            left_credits = int(left_item.get("credits") or 0)
            right_credits = int(right_item.get("credits") or 0)
            schedule[left].remove(left_item)
            schedule[right].remove(right_item)
            schedule[left].append(right_item)
            schedule[right].append(left_item)
            loads[left] += right_credits - left_credits
            loads[right] += left_credits - right_credits

    improve_scoped_semester_alignment()
    return schedule
