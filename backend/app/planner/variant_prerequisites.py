"""Prerequisite filtering primitives used by variant assembly.

These functions are intentionally independent of SQLAlchemy and project state:
the orchestrator supplies the already-loaded catalogue, evidence and title
normalizer.  Keeping the historical-edge cleanup here makes it testable and
prevents ranking code from silently changing prerequisite semantics.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any


def title_stems(
    title: object,
    *,
    normalize_title: Callable[[object], str],
    excluded_prefixes: Iterable[str],
) -> set[str]:
    """Return informative title stems used for a conservative edge check."""
    excluded = tuple(str(value) for value in excluded_prefixes)
    return {
        token[:7]
        for token in re.findall(r"[\w]+", normalize_title(title), flags=re.UNICODE)
        if len(token) >= 5 and not any(token.startswith(value) for value in excluded)
    }


def filter_supported_prerequisites(
    raw_prerequisites: Mapping[int, Iterable[int]],
    *,
    courses: Mapping[int, Any],
    aggregates: Mapping[int, Mapping[str, Any]],
    num_semesters: int,
    normalize_title: Callable[[object], str],
    excluded_prefixes: Iterable[str],
) -> dict[int, list[int]]:
    """Keep only earlier, evidenced or semantically related prerequisite edges."""
    filtered: dict[int, list[int]] = {}
    for course_id, prerequisite_ids in raw_prerequisites.items():
        course = courses.get(course_id)
        if course is None:
            continue
        course_stems = title_stems(
            getattr(course, "title", ""),
            normalize_title=normalize_title,
            excluded_prefixes=excluded_prefixes,
        )
        for prerequisite_id in prerequisite_ids:
            prerequisite = courses.get(prerequisite_id)
            if prerequisite is None:
                continue
            if int(getattr(prerequisite, "recommended_semester", 1) or 1) >= int(
                getattr(course, "recommended_semester", 1) or 1
            ):
                continue
            evidence_score = float(aggregates.get(prerequisite_id, {}).get("max") or 0.0)
            prerequisite_stems = title_stems(
                getattr(prerequisite, "title", ""),
                normalize_title=normalize_title,
                excluded_prefixes=excluded_prefixes,
            )
            if evidence_score < 0.25 and len(course_stems & prerequisite_stems) < 2:
                continue
            filtered.setdefault(course_id, []).append(prerequisite_id)
    return filtered


def make_course_depth(
    prerequisites: Mapping[int, Iterable[int]],
    *,
    courses: Mapping[int, Any],
    num_semesters: int,
) -> Callable[[int], int]:
    """Build a memoized prerequisite depth function with cycle protection."""
    cache: dict[int, int] = {}

    def depth(course_id: int, path: frozenset[int] = frozenset()) -> int:
        if course_id in cache:
            return cache[course_id]
        if course_id in path or course_id not in courses:
            return num_semesters + 1
        predecessor_ids = tuple(prerequisites.get(course_id, ()))
        value = 0 if not predecessor_ids else 1 + max(
            depth(predecessor_id, path | {course_id})
            for predecessor_id in predecessor_ids
        )
        cache[course_id] = value
        return value

    return depth
