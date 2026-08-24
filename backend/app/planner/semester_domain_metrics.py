"""Pure metrics used by the final domain-quota repair."""

from __future__ import annotations

from typing import Any, Mapping


def domain_deficit(verification: Mapping[str, Any]) -> float:
    """Return the remaining credit deficit across all domain quotas."""

    return sum(
        max(
            0.0,
            float(row.get("required_credits") or 0.0)
            - float(row.get("tolerance_credits") or 0.0)
            - float(row.get("actual_credits") or 0.0),
        )
        for row in (verification.get("domain_quota_violations") or [])
    )


def non_domain_hard_count(verification: Mapping[str, Any]) -> int:
    """Count hard violations unrelated to the domain quota being repaired."""

    goso = verification.get("goso_compliance") or {}
    pedagogical = verification.get("pedagogical_audit") or {}
    return (
        len(verification.get("prerequisite_violations") or [])
        + len(verification.get("semester_load_violations") or [])
        + len(verification.get("credit_violations") or [])
        + len(goso.get("violations") or [])
        + int(verification.get("course_lo_violations") or 0)
        + len(pedagogical.get("lo_without_real_course") or [])
        + len(pedagogical.get("weak_courses") or [])
        + len(pedagogical.get("structural_foundations") or [])
        + len(pedagogical.get("semester_misplacements") or [])
    )


def scope_strength(values: set[str], group: str, direction: str) -> int:
    """Rank exact group evidence above direction-only evidence."""

    if group and group in values:
        return 3
    if direction and direction in values:
        return 2
    return 0
