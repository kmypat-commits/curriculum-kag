"""Pure policy/ranking primitives for variant selection.

The orchestration function keeps the mutable selection state, while these
helpers contain deterministic admission and ranking rules that can be tested
independently.
"""

from __future__ import annotations

from functools import partial
from typing import Callable, Mapping

from app.models.course import Course
from app.planner.course_policy import course_role_rank
from app.planner.domain_evidence import domain_label_matches
from app.planner.scheduler_utils import title_key
from app.planner.scheduler_domain_rules import has_foreign_professional_title


def project_domain_index(
    course: Course,
    project_domains: list[str],
    epvo_domain_index: Mapping[int, int],
) -> int | None:
    for index, project_domain in enumerate(project_domains):
        if domain_label_matches(course.domain, [project_domain]):
            return index
    mapped = epvo_domain_index.get(course.id)
    # EPVO imports use 1-based domain labels (1=primary, 2=secondary),
    # while planner quota arrays are zero-based. Normalize at this boundary
    # so secondary-domain candidates remain eligible for quota repair.
    if mapped in (0, 1):
        return mapped
    if mapped == 2:
        return 1
    return None


def project_domain_share(
    course: Course | None,
    domain_index: int,
    epvo_domain_shares: Mapping[int, tuple[float, float]],
    project_domain_index_fn,
    project_domains: list[str],
) -> float:
    if course is None:
        return 0.0
    # The selector and verifier must account for domain credits in exactly
    # the same way.  A catalogue discipline explicitly labelled with one
    # declared programme domain is full evidence for that domain; an EPVO
    # row linked to two scopes must not silently dilute it to (0.5, 0.5).
    # Keep fractional evidence only for a genuinely ambiguous/unlabelled
    # catalogue row, where the scoped EPVO mapping is the sole provenance.
    explicit_matches = [
        index
        for index, project_domain in enumerate(project_domains)
        if domain_label_matches(course.domain, [project_domain])
    ]
    if len(explicit_matches) == 1:
        return 1.0 if explicit_matches[0] == domain_index else 0.0
    shares = epvo_domain_shares.get(course.id)
    if shares is not None:
        return shares[domain_index]
    return 1.0 if project_domain_index_fn(course) == domain_index else 0.0


def build_domain_policy_callbacks(
    *,
    project_domains: list[str],
    epvo_domain_index: Mapping[int, int],
    epvo_domain_shares: Mapping[int, tuple[float, float]],
) -> tuple[Callable[[Course], int | None], Callable[[Course | None, int], float]]:
    """Bind domain evidence after the scoped EPVO index has been loaded.

    The planner first determines the programme scope, then receives normalized
    per-course domain evidence from that scope.  Constructing these callbacks
    before that step captures empty dictionaries and silently makes legitimate
    secondary-domain courses look unrelated.  Keeping the factory here makes
    the lifecycle explicit and testable.
    """
    domain_index = partial(
        project_domain_index,
        project_domains=project_domains,
        epvo_domain_index=epvo_domain_index,
    )
    domain_share = partial(
        project_domain_share,
        epvo_domain_shares=epvo_domain_shares,
        project_domain_index_fn=domain_index,
        project_domains=project_domains,
    )
    return domain_index, domain_share


def scope_rank(
    course: Course,
    epvo_scope_by_id: Mapping[int, int],
    epvo_scope: Mapping[str, int],
) -> int:
    return epvo_scope_by_id.get(course.id, epvo_scope.get(title_key(course.title), 0))


def priority_rank(
    course: Course | None,
    epvo_priority_by_id: Mapping[int, int],
    epvo_priority: Mapping[str, int],
) -> int:
    if course is None:
        return 0
    return epvo_priority_by_id.get(course.id, epvo_priority.get(title_key(course.title), 0))


def semester_stability_rank(
    course: Course | None,
    epvo_semester_values: Mapping[int, list[int]],
) -> float:
    if course is None:
        return 0.0
    values: list[int] = []
    course_code = str(course.course_id or "")
    if course_code.startswith("EPVO-"):
        try:
            values = epvo_semester_values.get(int(course_code.split("-", 1)[1]), [])
        except (TypeError, ValueError):
            values = []
    if not values:
        return 0.0
    return -float(max(values) - min(values)) + min(0.25, len(values) / 100.0)


def role_rank(course: Course | None, project_domains: list[str]) -> int:
    return course_role_rank(course, project_domains)


def foreign_scope_conflict(course: Course, domain_text: str) -> bool:
    # Keep cross-sector rejection in one shared policy.  This must apply
    # before the exact-EPVO-scope exception below; catalogue membership is
    # evidence of provenance, not proof that a sectoral course belongs to
    # this programme's professional profile.
    if has_foreign_professional_title(course, [domain_text]):
        return True
    text = title_key(" ".join(str(value or "") for value in (
        course.title, course.description, course.domain,
    )))
    topic_groups = (
        (("химич", "химия", "chemical", "chemistry"), ("хим", "chemical", "chemistry")),
        (("нефт", "газов", "petroleum", "oil and gas"), ("нефт", "газ", "petroleum")),
        (("горн", "геолог", "mining", "geology"), ("горн", "геолог", "mining")),
        (("медицин", "клинич", "пациент", "medical", "clinical"), ("медицин", "здрав", "medical", "health")),
        (("агро", "сельск", "растен", "почв", "crop", "soil"), ("агро", "сельск", "растен", "почв")),
        (("ветерин", "veterinary"), ("ветерин", "veterinary")),
        (("строител", "civil engineering", "construction"), ("строител", "construction")),
    )
    return any(
        any(marker in text for marker in topic_markers)
        and not any(marker in domain_text for marker in allowed_domain_markers)
        for topic_markers, allowed_domain_markers in topic_groups
    )


def course_matches_scope_theme(
    course: Course,
    project_domains: list[str],
    domain_text: str,
    ict_programme: bool,
    medical_programme: bool,
    agro_programme: bool,
) -> bool:
    if foreign_scope_conflict(course, domain_text):
        return False
    text = " ".join(str(value or "") for value in (
        course.title, course.description, course.domain,
    )).lower()
    if ict_programme:
        if any(marker in text for marker in (
            "здоров", "здравоохран", "пациент", "стоматолог", "клинич",
            "физи", "лабораторная физика", "теоретическая физика",
            "электродинами", "скалярн", "калибровоч", "философ",
            "общекультур", "лингвист", "языкозн",
        )):
            return any(marker in text for marker in (
                "информац", "цифр", "программир", "разработк", "алгоритм",
                "данные", "данных", "база данных", "кибер", "криптограф",
                "software", "digital", "data", "computer", "algorithm",
            ))
        return any(marker in text for marker in (
            "информац", "цифр", "программир", "разработк", "алгоритм",
            "данные", "данных", "база данных", "сеть", "кибер", "криптограф",
            "искусствен", "машинн", "software", "digital", "data", "computer",
            "algorithm", "network", "security", "математ", "алгебр", "исчислен",
            "статист", "вероятност", "дискрет", "логик", "оптимизац", "calculus",
            "algebra", "statistics", "probability",
        ))
    if medical_programme:
        return any(marker in text for marker in (
            "медицин", "клинич", "пациент", "здоров", "анатом", "физиолог",
            "фармак", "clinical", "health", "medical",
        ))
    if agro_programme:
        return any(marker in text for marker in (
            "агро", "сельск", "растен", "почв", "урож", "животн", "agro", "crop", "soil",
        ))
    return True


def strong_exact_scope_evidence(
    course: Course,
    aggregates: Mapping[int, Mapping[str, object]],
    scope_rank_fn,
    domain_text: str,
) -> bool:
    evidence = aggregates.get(course.id, {})
    return (
        not foreign_scope_conflict(course, domain_text)
        and bool(evidence.get("professional_lo_codes"))
        and (
            scope_rank_fn(course) >= 3
            or float(evidence.get("max") or 0.0) >= 0.8
        )
    )


def frontier_admissible(
    course: Course,
    *,
    is_project_domain,
    strong_exact_scope_evidence,
    aggregates: Mapping[int, Mapping[str, object]],
) -> bool:
    """Keep only evidence-backed rows available to the selector.

    The final admission boundary requires a credible professional LO link.
    Applying the same contract to quota reservations prevents a discipline
    from temporarily filling a domain quota and then being removed later by
    admission, which used to leave a valid-looking but unpublishable plan.
    """
    if not bool(aggregates.get(course.id, {}).get("professional_lo_codes")):
        return False
    return bool(is_project_domain(course)) or (
        str(course.course_id or "").startswith("EPVO-")
        and bool(strong_exact_scope_evidence(course))
    )
