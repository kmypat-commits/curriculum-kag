"""Deterministic, atomic admission of real course prerequisite chains.

The database-backed frontier builder uses this policy before presenting any
course as an LO or credit candidate to the joint optimiser.
"""

from __future__ import annotations

from collections.abc import Mapping, Set

from app.planner.joint_contract import Candidate


def prerequisite_closure(
    course_id: int,
    prerequisites: Mapping[int, tuple[int, ...]],
    admissible_ids: Set[int],
) -> tuple[int, ...] | None:
    """Return parents-before-child closure, or None for an invalid chain.

    Missing, cyclic, or independently inadmissible parents invalidate the
    *whole* child; silently shortening the chain would violate the verifier.
    """
    ordered: list[int] = []
    done: set[int] = set()
    visiting: set[int] = set()

    def visit(current: int) -> bool:
        if current in visiting or current not in admissible_ids or current not in prerequisites:
            return False
        if current in done:
            return True
        visiting.add(current)
        for parent in sorted(set(prerequisites[current])):
            if not visit(parent):
                visiting.remove(current)
                return False
        visiting.remove(current)
        done.add(current)
        ordered.append(current)
        return True

    return tuple(ordered) if visit(course_id) else None


def admit_candidate_chains(
    catalogue: Mapping[int, Candidate],
    ranked_ids: tuple[int, ...],
    *,
    duplicate_ids: Set[int],
    limit: int,
) -> tuple[tuple[Candidate, ...], dict[str, int]]:
    """Admit ranked roots atomically with every parent, under a hard cap.

    The caller has already applied programme-domain and education-level
    admission. A removed regulatory duplicate cannot contribute LO evidence.
    """
    if limit < 1:
        raise ValueError("frontier limit must be positive")
    available = set(catalogue).difference(duplicate_ids)
    parents = {cid: candidate.prerequisites for cid, candidate in catalogue.items()}
    selected: dict[int, Candidate] = {}
    exclusions = {
        "goso_duplicate": 0,
        "missing_or_inadmissible_prerequisite": 0,
        "illegal_prerequisite_semester": 0,
        "frontier_capacity": 0,
    }
    for course_id in ranked_ids:
        if course_id in duplicate_ids:
            exclusions["goso_duplicate"] += 1
            continue
        closure = prerequisite_closure(course_id, parents, available)
        if closure is None:
            exclusions["missing_or_inadmissible_prerequisite"] += 1
            continue
        earliest: dict[int, int] = {}
        for member in closure:
            course = catalogue[member]
            after = max(
                (earliest[parent] for parent in course.prerequisites),
                default=0,
            )
            legal = [semester for semester in course.allowed_semesters if semester > after]
            if not legal:
                exclusions["illegal_prerequisite_semester"] += 1
                break
            earliest[member] = min(legal)
        if len(earliest) != len(closure):
            continue
        if len(selected.keys() | set(closure)) > limit:
            exclusions["frontier_capacity"] += 1
            continue
        for member in closure:
            selected.setdefault(member, catalogue[member])
    return tuple(selected.values()), exclusions
