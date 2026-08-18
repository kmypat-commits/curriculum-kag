"""Deterministic ranking primitives for curriculum-plan variants."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


def ranked_unique_candidate_ids(
    candidate_ids: Iterable[int],
    *,
    rank: Callable[[int], tuple],
    title_for: Callable[[int], str],
    limit: int = 100,
) -> list[int]:
    """Rank candidates and retain one canonical representative per title."""
    result: list[int] = []
    seen_titles: set[str] = set()
    for course_id in sorted(candidate_ids, key=rank, reverse=True):
        title = title_for(course_id)
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        result.append(course_id)
        if len(result) >= limit:
            break
    return result
