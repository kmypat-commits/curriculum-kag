from __future__ import annotations

from typing import Dict, List

from sqlalchemy.orm import Session

from app.models.bridge_module import BridgeModule
from app.models.project import ProjectVersion
from app.planner.scheduler_utils import (
    course_dependents as _course_dependents,
    move_item as _move_item,
    schedule_loads as _schedule_loads,
    semester_by_course as _semester_by_course,
    swap_items as _swap_items,
)
from app.planner.semester_rules import (
    foundation_max_semester as _foundation_max_semester,
    minimum_appropriate_semester as _item_minimum_appropriate_semester,
)



def _relocate_bounded_bridges(schedule: Dict[int, List[Dict]], num_semesters: int, nominal_load: int, db: Session) -> Dict[int, List[Dict]]:
    """Move CORE/SECONDARY bridge modules back to their intended study window."""
    upper = nominal_load + 3
    loads = {
        semester: sum(int(item.get("credits") or 0) for item in items)
        for semester, items in schedule.items()
    }
    for current_semester in sorted(schedule):
        for item in list(schedule[current_semester]):
            bridge_id = item.get("bridge_module_id")
            if bridge_id is None:
                continue
            bridge = db.query(BridgeModule).filter(BridgeModule.id == bridge_id).first()
            if not bridge or not (bridge.course_id or "").startswith(("CORE_BRIDGE_", "SECONDARY_")):
                continue
            recommended = int(bridge.recommended_semester or item.get("recommended_semester") or 1)
            latest = min(
                num_semesters,
                recommended + (2 if (bridge.course_id or "").startswith("CORE_BRIDGE_") else 1),
            )
            if recommended <= current_semester <= latest:
                continue
            credits = int(item.get("credits") or 0)
            candidates = list(range(recommended, latest + 1))
            candidates.sort(key=lambda semester: (loads[semester] + credits > upper, abs(semester - recommended), loads[semester]))
            target = candidates[0]
            if target == current_semester:
                continue
            if not _move_item(schedule, current_semester, target, item):
                continue
            loads[current_semester] -= credits
            loads[target] += credits
    return schedule

def _rebalance_semester_load(schedule: Dict[int, List[Dict]], num_semesters: int, nominal_load: int) -> Dict[int, List[Dict]]:
    """Final load repair that preserves prerequisite order."""
    lower = nominal_load - 3
    upper = nominal_load + 3

    for _ in range(40):
        current_loads = _schedule_loads(schedule)
        overloaded = [s for s, load in current_loads.items() if load > upper]
        receivers = [s for s, load in current_loads.items() if load < upper]
        if not overloaded or not receivers:
            break
        moved = False
        course_semesters = _semester_by_course(schedule)
        child_map = _course_dependents(schedule)
        for donor in sorted(overloaded, key=lambda s: current_loads[s], reverse=True):
            for target in sorted((s for s in receivers if s != donor), key=lambda s: current_loads[s]):
                for item in sorted(list(schedule[donor]), key=lambda x: int(x.get("credits") or 0), reverse=True):
                    if item.get("regulatory_required"):
                        continue
                    if item.get("_scoped_epvo_semester") and item.get("recommended_semester"):
                        if abs(donor - int(item["recommended_semester"])) <= 1:
                            # A scoped course already sits inside its EPVO
                            # window; use another item for overload repair.
                            continue
                    credits = int(item.get("credits") or 0)
                    if current_loads[target] + credits > upper:
                        continue
                    if target < _item_minimum_appropriate_semester(item, num_semesters):
                        continue
                    latest = int(item.get("latest_semester") or num_semesters)
                    if target > latest:
                        continue
                    parent_semesters = [course_semesters.get(pid, 0) for pid in item.get("prerequisites") or []]
                    if parent_semesters and max(parent_semesters) >= target:
                        continue
                    cid = item.get("course_id")
                    child_semesters = [course_semesters.get(child_id, num_semesters + 1) for child_id in child_map.get(cid, [])]
                    if child_semesters and min(child_semesters) <= target:
                        continue
                    if not _move_item(schedule, donor, target, item):
                        continue
                    moved = True
                    break
                if moved:
                    break
            if moved:
                break
        if not moved:
            break
    for _ in range(40):
        current_loads = _schedule_loads(schedule)
        underloaded = [s for s, load in current_loads.items() if load < lower]
        donors = [s for s, load in current_loads.items() if load > lower]
        if not underloaded or not donors:
            break
        moved = False
        course_semesters = _semester_by_course(schedule)
        child_map = _course_dependents(schedule)
        for target in sorted(underloaded, key=lambda s: current_loads[s]):
            for donor in sorted((s for s in donors if s != target), key=lambda s: current_loads[s], reverse=True):
                for item in sorted(list(schedule[donor]), key=lambda x: int(x.get("credits") or 0)):
                    if item.get("regulatory_required"):
                        continue
                    if item.get("_scoped_epvo_semester") and item.get("recommended_semester"):
                        if abs(target - int(item["recommended_semester"])) > 1:
                            continue
                    credits = int(item.get("credits") or 0)
                    if current_loads[donor] - credits < lower:
                        continue
                    if current_loads[target] + credits > upper:
                        continue
                    if target < _item_minimum_appropriate_semester(item, num_semesters):
                        continue
                    latest = int(item.get("latest_semester") or num_semesters)
                    if target > latest:
                        continue
                    parent_semesters = [course_semesters.get(pid, 0) for pid in item.get("prerequisites") or []]
                    if parent_semesters and max(parent_semesters) >= target:
                        continue
                    cid = item.get("course_id")
                    child_semesters = [course_semesters.get(child_id, num_semesters + 1) for child_id in child_map.get(cid, [])]
                    if child_semesters and min(child_semesters) <= target:
                        continue
                    if not _move_item(schedule, donor, target, item):
                        continue
                    moved = True
                    break
                if moved:
                    break
            if moved:
                break
        if not moved:
            break

    # A whole-course move cannot repair common 26/34 or 26/32 splits when all
    # courses carry 3--5 credits.  Exchange a larger donor course for a smaller
    # receiver course, while preserving every prerequisite and semester bound.
    for _ in range(40):
        current_loads = _schedule_loads(schedule)
        underloaded = [s for s, load in current_loads.items() if load < lower]
        if not underloaded:
            break
        course_semesters = _semester_by_course(schedule)
        child_map = _course_dependents(schedule)
        swapped = False

        def can_place(item: Dict, target: int, overrides: Dict[int, int]) -> bool:
            if item.get("regulatory_required"):
                return False
            if item.get("_scoped_epvo_semester") and item.get("recommended_semester"):
                if abs(target - int(item["recommended_semester"])) > 1:
                    return False
            if target < _item_minimum_appropriate_semester(item, num_semesters):
                return False
            if target > int(item.get("latest_semester") or num_semesters):
                return False
            cid = item.get("course_id")
            parent_semesters = [
                overrides.get(pid, course_semesters.get(pid, 0))
                for pid in item.get("prerequisites") or []
            ]
            if parent_semesters and max(parent_semesters) >= target:
                return False
            child_semesters = [
                overrides.get(child_id, course_semesters.get(child_id, num_semesters + 1))
                for child_id in child_map.get(cid, [])
            ] if cid is not None else []
            return not child_semesters or min(child_semesters) > target

        for target in sorted(underloaded, key=lambda s: current_loads[s]):
            donors = sorted(
                (s for s in schedule if s != target and current_loads[s] > lower),
                key=lambda s: current_loads[s],
                reverse=True,
            )
            for donor in donors:
                for donor_item in sorted(schedule[donor], key=lambda row: int(row.get("credits") or 0), reverse=True):
                    donor_credits = int(donor_item.get("credits") or 0)
                    for target_item in sorted(schedule[target], key=lambda row: int(row.get("credits") or 0)):
                        target_credits = int(target_item.get("credits") or 0)
                        if donor_credits <= target_credits:
                            continue
                        new_target_load = current_loads[target] - target_credits + donor_credits
                        new_donor_load = current_loads[donor] - donor_credits + target_credits
                        if not (lower <= new_target_load <= upper and lower <= new_donor_load <= upper):
                            continue
                        overrides = {}
                        if donor_item.get("course_id") is not None:
                            overrides[int(donor_item["course_id"])] = target
                        if target_item.get("course_id") is not None:
                            overrides[int(target_item["course_id"])] = donor
                        if not can_place(donor_item, target, overrides) or not can_place(target_item, donor, overrides):
                            continue
                        if not _swap_items(schedule, donor, donor_item, target, target_item):
                            continue
                        swapped = True
                        break
                    if swapped:
                        break
                if swapped:
                    break
            if swapped:
                break
        if not swapped:
            break

    # Final local improvement: move a real course toward its scoped EPVO
    # semester when the move preserves load and the prerequisite DAG.  This is
    # deliberately conservative; it never trades away a hard invariant for a
    # better external similarity score.
    for _ in range(60):
        current_loads = _schedule_loads(schedule)
        course_semesters = _semester_by_course(schedule)
        child_map = _course_dependents(schedule)
        candidates = sorted(
            ((semester, item) for semester, items in schedule.items() for item in items),
            key=lambda pair: abs(
                int(pair[1].get("recommended_semester") or pair[0]) - pair[0]
            ),
            reverse=True,
        )
        moved = False
        for donor, item in candidates:
            if item.get("regulatory_required"):
                continue
            recommended = int(item.get("recommended_semester") or donor)
            target_order = sorted(
                (semester for semester in schedule if semester != donor),
                key=lambda semester: abs(semester - recommended),
            )
            for target in target_order:
                credits = int(item.get("credits") or 0)
                if current_loads[donor] - credits < lower or current_loads[target] + credits > upper:
                    continue
                if target < _item_minimum_appropriate_semester(item, num_semesters):
                    continue
                if target > int(item.get("latest_semester") or num_semesters):
                    continue
                parents = [course_semesters.get(pid, 0) for pid in item.get("prerequisites") or []]
                if parents and max(parents) >= target:
                    continue
                children = [course_semesters.get(cid, num_semesters + 1) for cid in child_map.get(item.get("course_id"), [])]
                if children and min(children) <= target:
                    continue
                old_distance = abs(donor - recommended)
                new_distance = abs(target - recommended)
                if new_distance >= old_distance:
                    continue
                if not _move_item(schedule, donor, target, item):
                    continue
                moved = True
                break
            if moved:
                break
        if not moved:
            break
    return schedule

def _strict_rebalance_max_load(schedule: Dict[int, List[Dict]], num_semesters: int, max_load: int) -> Dict[int, List[Dict]]:
    """Try to respect the user-entered maximum semester load exactly."""
    if max_load <= 0:
        return schedule

    for _ in range(80):
        current = _schedule_loads(schedule)
        overloaded = [semester for semester, load in current.items() if load > max_load]
        if not overloaded:
            break
        moved = False
        course_semesters = _semester_by_course(schedule)
        child_map = _course_dependents(schedule)
        for donor in sorted(overloaded, key=lambda semester: current[semester], reverse=True):
            for item in sorted(list(schedule[donor]), key=lambda row: int(row.get("credits") or 0)):
                if item.get("regulatory_required"):
                    continue
                if item.get("_scoped_epvo_semester") and item.get("recommended_semester"):
                    recommended = int(item["recommended_semester"])
                    # Keep evidence-backed courses in their ±1 window while
                    # strict max-load repair looks for flexible candidates.
                    if abs(donor - recommended) <= 1:
                        continue
                credits = int(item.get("credits") or 0)
                if credits <= 0:
                    continue
                latest = int(item.get("latest_semester") or num_semesters)
                earliest = _item_minimum_appropriate_semester(
                    item, num_semesters
                )
                parent_semesters = [course_semesters.get(pid, 0) for pid in item.get("prerequisites") or []]
                min_target = max([earliest, *(semester + 1 for semester in parent_semesters)])
                cid = item.get("course_id")
                child_semesters = [course_semesters.get(child_id, num_semesters + 1) for child_id in child_map.get(cid, [])]
                semantic_latest = _foundation_max_semester(item.get("title"), num_semesters)
                if item.get("prerequisites") or int(item.get("recommended_semester") or 0) >= 4:
                    semantic_latest = max(
                        semantic_latest,
                        min(num_semesters, int(item.get("recommended_semester") or 1) + 2),
                    )
                max_target = min([latest, semantic_latest, *(semester - 1 for semester in child_semesters)] or [latest])
                targets = [
                    semester for semester in range(min_target, max_target + 1)
                    if semester != donor and current.get(semester, 0) + credits <= max_load
                ]
                if not targets:
                    continue
                targets.sort(key=lambda semester: (abs(semester - int(item.get("recommended_semester") or semester)), current.get(semester, 0)))
                target = targets[0]
                if not _move_item(schedule, donor, target, item):
                    continue
                current[donor] -= credits
                current[target] += credits
                moved = True
                break
            if moved:
                break
        if not moved:
            # A direct move can be blocked when every early receiver is full.
            # Free one valid receiver by moving one of its flexible courses to
            # a later semester, then place the overloaded course.  This is a
            # bounded two-hop move; it never moves ГОСО units or breaks a
            # prerequisite edge.
            def can_place(candidate: Dict, target: int, overrides: Dict[int, int]) -> bool:
                if candidate.get("regulatory_required"):
                    return False
                if target < _item_minimum_appropriate_semester(candidate, num_semesters):
                    return False
                if target > int(candidate.get("latest_semester") or num_semesters):
                    return False
                semantic_latest = _foundation_max_semester(candidate.get("title"), num_semesters)
                if candidate.get("prerequisites") or int(candidate.get("recommended_semester") or 0) >= 4:
                    semantic_latest = max(
                        semantic_latest,
                        min(num_semesters, int(candidate.get("recommended_semester") or 1) + 2),
                    )
                if target > semantic_latest:
                    return False
                parents = [
                    overrides.get(pid, course_semesters.get(pid, 0))
                    for pid in candidate.get("prerequisites") or []
                ]
                if parents and max(parents) >= target:
                    return False
                cid = candidate.get("course_id")
                children = [
                    overrides.get(child, course_semesters.get(child, num_semesters + 1))
                    for child in child_map.get(cid, [])
                ] if cid is not None else []
                return not children or min(children) > target

            cascaded = False
            for donor in sorted(overloaded, key=lambda semester: current[semester], reverse=True):
                for donor_item in sorted(schedule[donor], key=lambda row: int(row.get("credits") or 0), reverse=True):
                    if donor_item.get("regulatory_required"):
                        continue
                    donor_credits = int(donor_item.get("credits") or 0)
                    for target in range(1, num_semesters + 1):
                        if target == donor or not can_place(donor_item, target, {}):
                            continue
                        for displaced in sorted(schedule[target], key=lambda row: int(row.get("credits") or 0)):
                            if displaced.get("regulatory_required"):
                                continue
                            displaced_credits = int(displaced.get("credits") or 0)
                            if current[target] - displaced_credits + donor_credits > max_load:
                                continue
                            for receiver in sorted(
                                (semester for semester in schedule if semester not in {donor, target}),
                                key=lambda semester: current[semester],
                            ):
                                if current[receiver] + displaced_credits > max_load:
                                    continue
                                overrides = {}
                                if donor_item.get("course_id") is not None:
                                    overrides[int(donor_item["course_id"])] = target
                                if displaced.get("course_id") is not None:
                                    overrides[int(displaced["course_id"])] = receiver
                                if not can_place(donor_item, target, overrides) or not can_place(displaced, receiver, overrides):
                                    continue
                                if not _move_item(schedule, donor, target, donor_item):
                                    continue
                                if not _move_item(schedule, target, receiver, displaced):
                                    _move_item(schedule, target, donor, donor_item)
                                    continue
                                cascaded = True
                                break
                            if cascaded:
                                break
                        if cascaded:
                            break
                    if cascaded:
                        break
                if cascaded:
                    break
            if not cascaded:
                break
    return schedule

def _trim_schedule_to_target_credits(schedule: Dict[int, List[Dict]], target_credits: int, db: Session) -> Dict[int, List[Dict]]:
    """Make the persisted schedule prefer the exact programme credit total."""
    def total() -> int:
        return sum(int(item.get("credits") or 0) for items in schedule.values() for item in items)

    for item in sorted(
        (item for items in schedule.values() for item in items if item.get("bridge_module_id") is not None),
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

    while total() > target_credits:
        excess = total() - target_credits
        selected_ids = {
            item.get("course_id")
            for items in schedule.values()
            for item in items
            if item.get("course_id") is not None
            and not item.get("regulatory_required")
        }
        protected = {
            prerequisite_id
            for items in schedule.values()
            for item in items
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in selected_ids
        }
        removable = [
            (semester, index, item)
            for semester, items in schedule.items()
            for index, item in enumerate(items)
            if item.get("course_id") is not None
            and not item.get("competency_required")
            and item.get("course_id") not in protected
            and int(item.get("credits") or 0) <= excess
        ]
        if not removable:
            break
        removable.sort(key=lambda row: (
            int(row[2].get("credits") or 0) != excess,
            -row[0],
            int(row[2].get("recommended_semester") or 99),
            int(row[2].get("course_id") or 0),
        ))
        semester, index, _ = removable[0]
        del schedule[semester][index]
    return schedule

def _shift_excess_load_to_balance_modules(
    schedule: Dict[int, List[Dict]],
    project_version: ProjectVersion,
    nominal_load: int,
    db: Session,
) -> Dict[int, List[Dict]]:
    """Reallocate only flexible bridge workload after whole-course balancing.

    Credits declared for a real EPVO discipline are immutable.  Earlier code
    could reduce a 9-credit clinical course to three credits and invent a
    six-credit load-shift module elsewhere; that produced a numerically valid
    but academically false curriculum.
    """
    upper = nominal_load + 3
    constraints = project_version.project.constraints_json or {}
    interdisciplinary = (
        str(constraints.get("program_type") or "standard").lower()
        in {"interdisciplinary", "joint"}
    )

    for _ in range(20):
        current = _schedule_loads(schedule)
        donors = [semester for semester, load in current.items() if load > upper]
        receivers = [semester for semester, load in current.items() if load < upper]
        if not donors or not receivers:
            break
        moved = False
        for donor_semester in sorted(donors, key=lambda semester: current[semester], reverse=True):
            excess = current[donor_semester] - upper
            if excess <= 0:
                continue
            donor_items = sorted(
                [
                    item for item in schedule[donor_semester]
                    if int(item.get("credits") or 0) > 3
                    and not item.get("regulatory_required")
                    and item.get("bridge_module_id") is not None
                ],
                key=lambda item: (
                    0 if item.get("bridge_module_id") is not None else 1,
                    0 if "выбор" in str(item.get("type") or "").lower() or "elective" in str(item.get("type") or "").lower() else 1,
                    -int(item.get("credits") or 0),
                ),
            )
            if not donor_items:
                continue
            def receiver_bridge(semester: int) -> Dict | None:
                candidates = [
                    item for item in schedule[semester]
                    if item.get("bridge_module_id") is not None
                    and int(item.get("credits") or 0) < 7
                ]
                return min(
                    candidates,
                    key=lambda item: int(item.get("credits") or 0),
                    default=None,
                )

            ordered_receivers = sorted(
                receivers,
                key=lambda semester: (
                    receiver_bridge(semester) is None,
                    current[semester],
                ),
            )
            for receiver_semester in ordered_receivers:
                room = upper - current[receiver_semester]
                if room <= 0:
                    continue
                donor = donor_items[0]
                shift = min(excess, room, int(donor.get("credits") or 0) - 3)
                if shift <= 0:
                    continue
                flexible_receiver = receiver_bridge(receiver_semester)
                if flexible_receiver is not None:
                    shift = min(
                        shift,
                        7 - int(flexible_receiver.get("credits") or 0),
                    )
                    if shift <= 0:
                        continue
                    donor["credits"] = int(donor.get("credits") or 0) - shift
                    donor_module = db.query(BridgeModule).filter(
                        BridgeModule.id == donor["bridge_module_id"]
                    ).first()
                    if donor_module:
                        donor_module.credits = donor["credits"]
                    flexible_receiver["credits"] = int(
                        flexible_receiver.get("credits") or 0
                    ) + shift
                    receiver_module = db.query(BridgeModule).filter(
                        BridgeModule.id == flexible_receiver["bridge_module_id"]
                    ).first()
                    if receiver_module:
                        receiver_module.credits = flexible_receiver["credits"]
                    moved = True
                    break
                if shift < 3 or interdisciplinary:
                    continue
                donor["credits"] = int(donor.get("credits") or 0) - shift
                donor_module = db.query(BridgeModule).filter(
                    BridgeModule.id == donor["bridge_module_id"]
                ).first()
                if donor_module:
                    donor_module.credits = donor["credits"]

                code = f"AUTO_LOAD_SHIFT_{project_version.id}_{receiver_semester}"
                module = db.query(BridgeModule).filter(
                    BridgeModule.project_version_id == project_version.id,
                    BridgeModule.course_id == code,
                ).first()
                if module is None:
                    module = BridgeModule(
                        project_version_id=project_version.id,
                        course_id=code,
                        title=f"Интегрированный модуль выравнивания нагрузки семестра {receiver_semester}",
                        goal="Перенести часть проектной и самостоятельной работы из перегруженного семестра.",
                        description="Модуль фиксирует самостоятельную работу, портфолио и консультации по дисциплинам перегруженного семестра.",
                        credits=shift,
                        recommended_semester=receiver_semester,
                        learning_outcomes=["Подготовить портфолио подтверждений по результатам обучения семестра."],
                        topics=["Портфолио", "Самостоятельная работа", "Консультации", "Рефлексия"],
                        prerequisites=[],
                        assessment_methods=["портфолио", "рефлексивный отчёт"],
                        source_chunks_json=[],
                        generation_params_json={
                            "mode": "load_shift_repair",
                            "from_semester": donor_semester,
                            "from_course_id": donor.get("course_id"),
                            "from_bridge_module_id": donor.get("bridge_module_id"),
                            "from_title": donor.get("title"),
                            "shifted_credits": shift,
                        },
                        target_los=[
                            lo.lo_code for lo in project_version.learning_outcomes
                            if not str(lo.lo_code or "").startswith("LO-GOSO-")
                        ],
                    )
                    db.add(module)
                    db.flush()
                    schedule[receiver_semester].append({
                        "bridge_module_id": module.id,
                        "title": module.title,
                        "domain": "interdisciplinary",
                        "credits": shift,
                        "recommended_semester": receiver_semester,
                        "latest_semester": receiver_semester,
                        "prerequisites": [],
                        "type": "bridge",
                    })
                else:
                    existing = next((item for item in schedule[receiver_semester] if item.get("bridge_module_id") == module.id), None)
                    module.credits = int(module.credits or 0) + shift
                    if existing:
                        existing["credits"] = int(existing.get("credits") or 0) + shift
                    else:
                        schedule[receiver_semester].append({
                            "bridge_module_id": module.id,
                            "title": module.title,
                            "domain": "interdisciplinary",
                            "credits": shift,
                            "recommended_semester": receiver_semester,
                            "latest_semester": receiver_semester,
                            "prerequisites": [],
                            "type": "bridge",
                        })
                moved = True
                break
            if moved:
                break
        if not moved:
            break
    return schedule

def _repair_underloaded_semesters_with_bridges(
    schedule: Dict[int, List[Dict]],
    project_version: ProjectVersion,
    nominal_load: int,
    target_credits: int,
    maximum_credits: int,
    db: Session,
) -> Dict[int, List[Dict]]:
    """Repair a residual low semester using only flexible bridge workload.

    Whole-course moves remain preferable.  This final repair transfers credits
    between 3--7 credit bridge modules and uses the user-approved total-credit
    tolerance only for a remainder that cannot be transferred safely.
    """
    lower = nominal_load - 3

    bridge_ids = {
        int(item["bridge_module_id"])
        for items in schedule.values()
        for item in items
        if item.get("bridge_module_id") is not None
    }
    modules = {
        module.id: module
        for module in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids or [-1])).all()
    }

    def bridge_kind(item: Dict) -> str:
        module = modules.get(item.get("bridge_module_id"))
        code = str(module.course_id or "") if module else ""
        if code.startswith("SECONDARY_"):
            return "secondary"
        if code.startswith("CORE_BRIDGE_"):
            return "core"
        return "other"

    for target_semester in sorted(schedule):
        current = _schedule_loads(schedule)
        need = max(0, lower - current.get(target_semester, 0))
        if need <= 0:
            continue
        # Prefer moving a complete flexible bridge.  This keeps every module
        # inside the valid 3--7 credit range and handles residual 26/31 loads
        # without inventing a one-credit pseudo-module.
        whole_bridge_donors = sorted(
            [
                (semester, item)
                for semester, items in schedule.items()
                if semester != target_semester
                for item in items
                if item.get("bridge_module_id") is not None
                and not (item.get("prerequisites") or [])
                and current[semester] - int(item.get("credits") or 0) >= lower
                and current[target_semester] + int(item.get("credits") or 0) <= nominal_load + 3
                and target_semester <= int(item.get("latest_semester") or len(schedule))
            ],
            key=lambda pair: (
                abs(int(pair[1].get("credits") or 0) - need),
                -current[pair[0]],
            ),
        )
        if whole_bridge_donors:
            donor_semester, whole_bridge = whole_bridge_donors[0]
            _move_item(schedule, donor_semester, target_semester, whole_bridge)
            current = _schedule_loads(schedule)
            need = max(0, lower - current.get(target_semester, 0))
            if need <= 0:
                continue
        receivers = sorted(
            [
                item for item in schedule[target_semester]
                if item.get("bridge_module_id") is not None and int(item.get("credits") or 0) < 7
            ],
            key=lambda item: ({"secondary": 0, "other": 1, "core": 2}[bridge_kind(item)], int(item.get("credits") or 0)),
        )
        if not receivers:
            continue
        receiver = receivers[0]
        receiver_kind = bridge_kind(receiver)
        donors = sorted(
            [
                (semester, item)
                for semester, items in schedule.items()
                if semester != target_semester
                for item in items
                if item.get("bridge_module_id") is not None
                and int(item.get("credits") or 0) > 3
                and bridge_kind(item) != receiver_kind
            ],
            key=lambda pair: (0 if bridge_kind(pair[1]) == "core" else 1, -int(pair[1].get("credits") or 0)),
        )
        for donor_semester, donor in donors:
            if need <= 0:
                break
            current = _schedule_loads(schedule)
            transferable = min(
                int(donor.get("credits") or 0) - 3,
                current[donor_semester] - lower,
                7 - int(receiver.get("credits") or 0),
                need,
            )
            if transferable <= 0:
                continue
            donor["credits"] = int(donor.get("credits") or 0) - transferable
            receiver["credits"] = int(receiver.get("credits") or 0) + transferable
            modules[int(donor["bridge_module_id"])].credits = donor["credits"]
            modules[int(receiver["bridge_module_id"])].credits = receiver["credits"]
            need -= transferable

        if need > 0:
            current_total = sum(_schedule_loads(schedule).values())
            increase = min(
                need,
                7 - int(receiver.get("credits") or 0),
                max(0, maximum_credits - current_total),
            )
            if increase > 0:
                receiver["credits"] = int(receiver.get("credits") or 0) + increase
                modules[int(receiver["bridge_module_id"])].credits = receiver["credits"]
    return schedule
