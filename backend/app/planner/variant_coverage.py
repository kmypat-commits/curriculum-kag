"""Coverage calculations shared by variant repair and quality gates."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence


def coverage_state(
    values: Sequence[dict],
    *,
    lo_codes: Sequence[str],
    score_by_course: Mapping[int, Mapping[str, float]],
    required_coverage: float,
) -> tuple[dict[str, float], dict[str, float], list[str]]:
    """Return probabilistic LO coverage, strongest evidence and missing codes."""
    products = {code: 1.0 for code in lo_codes}
    maximums = {code: 0.0 for code in lo_codes}
    for item in values:
        course_id = int(item.get("course_id") or 0)
        for code, score in score_by_course.get(course_id, {}).items():
            bounded = max(0.0, min(1.0, float(score)))
            products[code] *= 1.0 - bounded
            maximums[code] = max(maximums[code], bounded)
    coverage = {code: 1.0 - product for code, product in products.items()}
    missing_codes = [
        code
        for code, value in coverage.items()
        if value + 1e-9 < required_coverage
        or maximums[code] + 1e-9 < 0.5
    ]
    return coverage, maximums, missing_codes


def coverage_objective(
    values: Sequence[dict],
    *,
    state: Callable[[Sequence[dict]], tuple[dict[str, float], dict[str, float], list[str]]],
) -> tuple:
    """Lexicographic objective used when evaluating an LO-gap replacement."""
    coverage, maximums, missing_codes = state(values)
    return (
        len(coverage) - len(missing_codes),
        min(coverage.values(), default=0.0),
        sum(coverage.values()),
        sum(maximums.values()),
    )
