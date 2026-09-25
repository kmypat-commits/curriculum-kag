"""Database-free input and output contract for joint curriculum assembly."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    course_id: int
    item: dict
    allowed_semesters: tuple[int, ...]
    prerequisites: tuple[int, ...]
    lo_scores: dict[str, float]
    domain_shares: tuple[float, float]
    utility: float


@dataclass(frozen=True)
class PlanningProblem:
    candidates: tuple[Candidate, ...]
    fixed_schedule: dict[int, list[dict]]
    required_los: tuple[str, ...]
    target_credits: int
    credit_tolerance: int
    min_load: float
    max_load: float
    domain_minima: tuple[float, float]
    exclusions: dict[str, int]
    frontier_truncated: bool

    @property
    def candidates_by_id(self) -> dict[int, Candidate]:
        return {candidate.course_id: candidate for candidate in self.candidates}


@dataclass(frozen=True)
class PlanningResult:
    schedule: dict[int, list[dict]]
    selected_course_ids: frozenset[int]
    objective: float
    solver_seconds: float


class PlanningFailure(RuntimeError):
    def __init__(self, status: str, details: dict):
        super().__init__(status)
        self.status = status
        self.details = details
