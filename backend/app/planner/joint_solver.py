"""Database-free course-and-semester mixed-integer feasibility model."""

from __future__ import annotations

import time
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_array

from app.planner.joint_contract import PlanningFailure, PlanningProblem, PlanningResult
from app.planner.verifier import MATCH_THRESHOLD, REAL_COURSE_LO_THRESHOLD


def solve_joint(
    problem: PlanningProblem,
    *,
    time_limit_seconds: float,
    forbidden_sets: tuple[frozenset[int], ...] = (),
) -> PlanningResult:
    """Select only a fully feasible real-course set and its semester schedule.

    A bounded or time-limited search that yields no integral solution is never
    described as global curriculum infeasibility.
    """
    started = time.perf_counter()
    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be positive")
    candidates = tuple(sorted(problem.candidates, key=lambda course: course.course_id))
    by_id = {course.course_id: course for course in candidates}
    if len(by_id) != len(candidates):
        raise PlanningFailure("invalid_candidate_data", {"reason": "duplicate_course_id"})
    semesters = tuple(sorted(problem.fixed_schedule))
    if not semesters or semesters != tuple(range(1, len(semesters) + 1)):
        raise PlanningFailure("invalid_candidate_data", {"reason": "non_contiguous_semesters"})
    fixed_semester = {
        int(item["course_id"]): semester
        for semester, items in problem.fixed_schedule.items()
        for item in items if item.get("course_id") is not None
    }
    x_index = {course.course_id: index for index, course in enumerate(candidates)}
    y_index: dict[tuple[int, int], int] = {}
    for course in candidates:
        if not course.allowed_semesters or any(
            semester not in problem.fixed_schedule for semester in course.allowed_semesters
        ):
            raise PlanningFailure("invalid_candidate_data", {
                "reason": "invalid_allowed_semester", "course_id": course.course_id,
            })
        if int(course.item.get("credits") or 0) <= 0:
            raise PlanningFailure("invalid_candidate_data", {
                "reason": "non_positive_credits", "course_id": course.course_id,
            })
        if max(course.lo_scores.values(), default=0.0) < MATCH_THRESHOLD:
            raise PlanningFailure("invalid_candidate_data", {
                "reason": "unverified_course_evidence", "course_id": course.course_id,
            })
        for semester in sorted(set(course.allowed_semesters)):
            y_index[course.course_id, semester] = len(candidates) + len(y_index)
    nvars = len(candidates) + len(y_index)
    if nvars == 0:
        raise PlanningFailure(
            "no_solution_in_bounded_frontier" if problem.frontier_truncated
            else "infeasible_with_complete_frontier",
            {"reason": "empty_candidate_frontier", "exclusions": problem.exclusions},
        )

    sparse_rows: list[dict[int, float]] = []
    lower: list[float] = []
    upper: list[float] = []

    def add(coefficients: dict[int, float], minimum: float, maximum: float) -> None:
        sparse_rows.append(coefficients)
        lower.append(minimum)
        upper.append(maximum)

    for course in candidates:
        cid = course.course_id
        assign = {y_index[cid, semester]: 1.0 for semester in course.allowed_semesters}
        assign[x_index[cid]] = -1.0
        add(assign, 0.0, 0.0)
        for parent_id in course.prerequisites:
            if parent_id in by_id:
                add({x_index[cid]: 1.0, x_index[parent_id]: -1.0}, -np.inf, 0.0)
                for semester in course.allowed_semesters:
                    ordering = {y_index[cid, semester]: 1.0}
                    for earlier in by_id[parent_id].allowed_semesters:
                        if earlier < semester:
                            ordering[y_index[parent_id, earlier]] = -1.0
                    add(ordering, -np.inf, 0.0)
            elif parent_id in fixed_semester:
                for semester in course.allowed_semesters:
                    if fixed_semester[parent_id] >= semester:
                        add({y_index[cid, semester]: 1.0}, 0.0, 0.0)
            else:
                raise PlanningFailure("invalid_candidate_data", {
                    "reason": "missing_prerequisite", "course_id": cid,
                    "prerequisite_id": parent_id,
                })

    total_row: dict[int, float] = {}
    for semester in semesters:
        fixed_credits = sum(int(item.get("credits") or 0)
                            for item in problem.fixed_schedule[semester])
        row = {
            y_index[course.course_id, semester]: float(course.item["credits"])
            for course in candidates if (course.course_id, semester) in y_index
        }
        add(row, problem.min_load - fixed_credits,
            problem.max_load - fixed_credits)
        total_row.update(row)
    fixed_total = sum(int(item.get("credits") or 0)
                      for items in problem.fixed_schedule.values() for item in items)
    add(total_row, problem.target_credits - fixed_total,
        problem.target_credits + problem.credit_tolerance - fixed_total)

    for code in problem.required_los:
        covering = {
            x_index[course.course_id]: 1.0
            for course in candidates
            if course.lo_scores.get(code, 0.0) >= REAL_COURSE_LO_THRESHOLD
        }
        add(covering, 1.0, np.inf)
    for index, minimum in enumerate(problem.domain_minima):
        if minimum <= 0:
            continue
        shares = {
            x_index[course.course_id]:
                float(course.item["credits"]) * course.domain_shares[index]
            for course in candidates if course.domain_shares[index] > 0
        }
        add(shares, float(minimum), np.inf)

    all_ids = set(by_id)
    for forbidden in forbidden_sets:
        exact = set(forbidden) & all_ids
        # This is a no-good cut for exactly one previous real-course set.
        add({x_index[cid]: (1.0 if cid in exact else -1.0) for cid in sorted(all_ids)},
            -np.inf, len(exact) - 1)

    data: list[float] = []
    row_ids: list[int] = []
    column_ids: list[int] = []
    for row_number, row in enumerate(sparse_rows):
        for column, value in row.items():
            if value:
                row_ids.append(row_number)
                column_ids.append(column)
                data.append(value)
    matrix = coo_array(
        (np.asarray(data, dtype=float),
         (np.asarray(row_ids, dtype=np.int32), np.asarray(column_ids, dtype=np.int32))),
        shape=(len(sparse_rows), nvars),
    ).tocsr()
    objective = np.zeros(nvars, dtype=float)
    for index, course in enumerate(candidates):
        objective[index] = -float(course.utility) + 1e-5 + index * 1e-9
        recommended = int(course.item.get("recommended_semester") or 0)
        for semester in course.allowed_semesters:
            objective[y_index[course.course_id, semester]] = (
                1e-4 * abs(semester - recommended) if recommended else 0.0
            )
    result = milp(
        c=objective, integrality=np.ones(nvars, dtype=np.int32),
        bounds=Bounds(np.zeros(nvars), np.ones(nvars)),
        constraints=LinearConstraint(matrix, np.asarray(lower), np.asarray(upper)),
        options={"time_limit": float(time_limit_seconds), "presolve": True},
    )
    if result.status != 0 or result.x is None:
        status = (
            "solver_timeout" if result.status == 1 and "time" in str(result.message).lower()
            else "solver_limit" if result.status == 1
            else "no_solution_in_bounded_frontier" if result.status == 2 and problem.frontier_truncated
            else "infeasible_with_complete_frontier" if result.status == 2
            else "solver_error"
        )
        raise PlanningFailure(status, {
            "scipy_status": int(result.status), "message": str(result.message),
            "frontier_truncated": problem.frontier_truncated,
            "candidate_count": len(candidates), "exclusions": problem.exclusions,
        })
    if np.max(np.abs(result.x - np.round(result.x))) > 1e-6:
        raise PlanningFailure("solver_error", {"reason": "fractional_solution"})
    schedule = {semester: [dict(item) for item in problem.fixed_schedule[semester]]
                for semester in semesters}
    selected: set[int] = set()
    for course in candidates:
        if result.x[x_index[course.course_id]] < 0.5:
            continue
        selected.add(course.course_id)
        placements = [semester for semester in course.allowed_semesters
                      if result.x[y_index[course.course_id, semester]] > 0.5]
        if len(placements) != 1:
            raise PlanningFailure("solver_error", {
                "reason": "invalid_placement", "course_id": course.course_id,
            })
        schedule[placements[0]].append(dict(course.item))
    return PlanningResult(
        schedule=schedule, selected_course_ids=frozenset(selected),
        objective=float(result.fun), solver_seconds=time.perf_counter() - started,
    )
