"""Shared, lossless accounting of EPVO evidence for two-domain programmes."""

from __future__ import annotations

import re
from typing import Iterable, Tuple


_DOMAIN_ALIASES = {
    "healthcare": ("health", "medicine", "медицин", "здрав", "медицина", "денсаулық"),
    "agriculture": ("agri", "agro", "farm", "сельск", "аграр", "агроном", "агроп", "ауыл"),
    "information and communication technologies": (
        "information", "communication", "ict", "computer", "it", "ақпарат", "информ",
    ),
    "business and management": (
        "business", "management", "эконом", "управ", "менедж", "бизнес",
    ),
}


def _label_contains(value: str, term: str) -> bool:
    """Match short aliases as whole tokens and language stems as fragments."""
    normalized = str(term or "").casefold().strip()
    if not normalized:
        return False
    # `it` is a valid ICT abbreviation but a very common pair of letters in
    # ordinary words such as Literature and Hospitality.  Do not use a
    # substring rule for compact abbreviations.
    if len(normalized) <= 3:
        return normalized in re.findall(r"[\w-]+", value, flags=re.UNICODE)
    return normalized in value


def domain_label_matches(label: str | None, project_domains: Iterable[str]) -> bool:
    """Match common EPVO domain labels without treating aliases as new domains."""
    value = str(label or "").casefold().strip()
    if not value:
        return False
    for project_domain in project_domains:
        key = str(project_domain or "").casefold().strip()
        if not key:
            continue
        aliases = _DOMAIN_ALIASES.get(key, ())
        if not aliases:
            if any(token in key for token in ("health", "здрав", "медицин", "medicine")):
                aliases = _DOMAIN_ALIASES["healthcare"]
            elif any(token in key for token in ("agri", "agro", "сельск", "аграр", "агроном", "ауыл")):
                aliases = _DOMAIN_ALIASES["agriculture"]
            elif any(token in key for token in ("information", "communication", "информа", "ақпарат", "ict")):
                aliases = _DOMAIN_ALIASES["information and communication technologies"]
            elif any(token in key for token in ("business", "management", "бизнес", "управ", "эконом")):
                aliases = _DOMAIN_ALIASES["business and management"]
        if (
            _label_contains(value, key)
            or _label_contains(key, value)
            or any(_label_contains(value, alias) for alias in aliases)
        ):
            return True
    return False


def is_information_technology_domain(label: str | None) -> bool:
    """Classify a declared project domain without a raw substring heuristic."""
    return domain_label_matches(label, ["information and communication technologies"])


def domain_credit_shares(primary_scope: int, secondary_scope: int) -> Tuple[float, float]:
    """Allocate one course credit once across selected EPVO domains.

    A canonical EPVO discipline can occur in both selected groups or
    directions. Assigning it fully to both domains inflates the quota, while
    assigning every tie to domain 1 systematically starves domain 2.
    """
    primary = max(0, int(primary_scope or 0))
    secondary = max(0, int(secondary_scope or 0))
    total = primary + secondary
    if total <= 0:
        return (0.0, 0.0)
    return (primary / total, secondary / total)


def course_domain_shares(
    *,
    item_domain: str | None,
    canonical_domain: str | None,
    project_domains: tuple[str, str],
    scoped_shares: tuple[float, float] | None,
) -> tuple[float, float]:
    """Resolve the same one-course domain contribution used by the verifier."""
    canonical = str(canonical_domain or "")
    combined = " ".join((str(item_domain or ""), canonical)).casefold().strip()
    canonical_matches = tuple(
        domain_label_matches(canonical, [domain]) for domain in project_domains
    )
    explicit_matches = tuple(
        domain_label_matches(combined, [domain]) for domain in project_domains
    )
    if canonical_matches[1] and not canonical_matches[0]:
        return (0.0, 1.0)
    if canonical_matches[0] and not canonical_matches[1]:
        return (1.0, 0.0)
    if scoped_shares is not None:
        if explicit_matches[1] and not explicit_matches[0]:
            return (0.0, 1.0)
        if explicit_matches[0] and not explicit_matches[1]:
            return (1.0, 0.0)
        return scoped_shares
    if explicit_matches[0]:
        return (1.0, 0.0)
    if explicit_matches[1]:
        return (0.0, 1.0)
    return (0.0, 0.0)


def domain_has_evidence(shares: Iterable[float], domain_index: int) -> bool:
    values = tuple(float(value or 0.0) for value in shares)
    return 0 <= domain_index < len(values) and values[domain_index] > 0.0
