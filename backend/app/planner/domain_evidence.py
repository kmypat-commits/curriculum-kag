"""Shared, lossless accounting of EPVO evidence for two-domain programmes."""

from __future__ import annotations

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
        if key in value or value in key or any(alias in value for alias in aliases):
            return True
    return False


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


def domain_has_evidence(shares: Iterable[float], domain_index: int) -> bool:
    values = tuple(float(value or 0.0) for value in shares)
    return 0 <= domain_index < len(values) and values[domain_index] > 0.0
