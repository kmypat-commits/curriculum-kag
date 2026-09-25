"""Solve a complete semester assignment when local load moves are insufficient."""

from __future__ import annotations

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from app.planner.semester_rules import foundation_max_semester, minimum_appropriate_semester


def repair_schedule_globally(schedule, *, num_semesters, nominal_load):
    """Return a credit-preserving legal assignment, or None if none is found.

    The optimization moves whole existing courses only. Regulatory rows stay
    fixed; no course or credit is created, removed, or resized.
    """
    lower, upper = nominal_load - 3, nominal_load + 3
    rows = [(semester, item) for semester, items in schedule.items() for item in items]
    slots = []
    by_course = {}
    for row_index, (current, item) in enumerate(rows):
        if item.get("course_id") is not None:
            by_course[int(item["course_id"])] = row_index
        if item.get("regulatory_required"):
            allowed = [current]
        else:
            earliest = minimum_appropriate_semester(item, num_semesters)
            latest = min(
                num_semesters,
                int(item.get("latest_semester") or num_semesters),
                foundation_max_semester(item.get("title"), num_semesters),
            )
            allowed = list(range(earliest, latest + 1))
        if not allowed:
            return None
        slots.extend((row_index, semester) for semester in allowed)

    size = len(slots)
    constraints = []
    minima = []
    maxima = []
    for row_index in range(len(rows)):
        coefficients = np.zeros(size)
        for column, (item_index, _) in enumerate(slots):
            if item_index == row_index:
                coefficients[column] = 1
        constraints.append(coefficients)
        minima.append(1)
        maxima.append(1)

    for semester in range(1, num_semesters + 1):
        coefficients = np.zeros(size)
        for column, (row_index, candidate_semester) in enumerate(slots):
            if candidate_semester == semester:
                coefficients[column] = int(rows[row_index][1].get("credits") or 0)
        constraints.append(coefficients)
        minima.append(lower)
        maxima.append(upper)

    for child_index, (_, child) in enumerate(rows):
        for parent_id in child.get("prerequisites") or []:
            parent_index = by_course.get(int(parent_id))
            if parent_index is None:
                continue
            coefficients = np.zeros(size)
            for column, (row_index, semester) in enumerate(slots):
                if row_index == child_index:
                    coefficients[column] += semester
                if row_index == parent_index:
                    coefficients[column] -= semester
            constraints.append(coefficients)
            minima.append(1)
            maxima.append(np.inf)

    costs = np.array([
        100 * (semester != rows[row_index][0])
        + abs(semester - int(rows[row_index][1].get("recommended_semester") or semester))
        + semester * 0.001
        for row_index, semester in slots
    ], dtype=float)
    result = milp(
        costs,
        integrality=np.ones(size),
        bounds=Bounds(np.zeros(size), np.ones(size)),
        constraints=LinearConstraint(np.vstack(constraints), minima, maxima),
        options={"time_limit": 5},
    )
    if result.x is None or result.status != 0:
        return None
    repaired = {semester: [] for semester in range(1, num_semesters + 1)}
    for column, (row_index, semester) in enumerate(slots):
        if result.x[column] > 0.5:
            repaired[semester].append(rows[row_index][1])
    return repaired
