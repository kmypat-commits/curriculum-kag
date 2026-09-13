"""Auditable invariants and bounded fixed-point utilities for planner repairs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable, Any


def schedule_fingerprint(schedule: dict) -> str:
    canonical = []
    for semester, items in sorted(schedule.items(), key=lambda row: int(row[0])):
        rows = [
            (item.get("course_id"), item.get("bridge_module_id"), int(item.get("credits") or 0))
            for item in (items or [])
        ]
        # Real courses and generated bridge items use different identifiers;
        # one side is legitimately None. Raw tuple sorting would compare None
        # with int and crash only on mixed real/bridge plans.
        rows.sort(key=lambda row: (
            "" if row[0] is None else str(row[0]),
            "" if row[1] is None else str(row[1]),
            row[2],
        ))
        canonical.append([int(semester), rows])
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:16]


def invariant_errors(schedule: dict, num_semesters: int) -> list[str]:
    errors = []
    seen_courses = set()
    for semester, items in schedule.items():
        if int(semester) < 1 or int(semester) > int(num_semesters):
            errors.append(f"semester_out_of_range:{semester}")
        for item in items or []:
            credits = int(item.get("credits") or 0)
            if credits <= 0:
                errors.append("non_positive_credits")
            course_id = item.get("course_id")
            if course_id is not None:
                if course_id in seen_courses:
                    errors.append(f"duplicate_course:{course_id}")
                seen_courses.add(course_id)
    return sorted(set(errors))


@dataclass
class InvariantLedger:
    num_semesters: int
    stages: list[dict[str, Any]] = field(default_factory=list)

    def record(self, stage: str, schedule: dict) -> None:
        errors = invariant_errors(schedule, self.num_semesters)
        entry = {"stage": stage, "fingerprint": schedule_fingerprint(schedule), "errors": errors}
        self.stages.append(entry)
        if errors:
            raise ValueError(f"Planner invariant violation at {stage}: {', '.join(errors)}")

    def as_dict(self) -> dict[str, Any]:
        return {"passed": all(not row["errors"] for row in self.stages), "stages": self.stages}


def run_to_fixed_point(state: Any, transition: Callable[[Any], Any], fingerprint: Callable[[Any], Any], max_iterations: int = 20) -> tuple[Any, int]:
    """Apply a repair until stable; reject cycles and unbounded repair loops."""
    seen = set()
    current = state
    for iteration in range(1, max_iterations + 1):
        marker = fingerprint(current)
        if marker in seen:
            raise RuntimeError("Repair cycle detected before reaching a fixed point")
        seen.add(marker)
        updated = transition(current)
        if fingerprint(updated) == marker:
            return updated, iteration
        current = updated
    raise RuntimeError(f"Repair did not reach a fixed point within {max_iterations} iterations")
