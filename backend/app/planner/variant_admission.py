"""Admission predicates shared by the variant-selection pipeline.

The predicate is intentionally pure with respect to the database.  Retrieval
builds the evidence maps first, then this module applies the education-level,
scope, expert-evidence and curriculum-role guards consistently to every
variant and final repair pass.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from app.models.course import Course
from app.planner.domain_evidence import is_information_technology_domain


def remove_weak_general_items(
    items: list[dict],
    *,
    professional_scope: bool,
    courses: Mapping[int, Course],
    project_domains: Sequence[str],
    aggregates: Mapping[int, Mapping[str, object]],
    curriculum_role: Callable[[Course, Sequence[str]], str],
    min_general_lo_evidence: float,
) -> list[dict]:
    """Drop generic courses without sufficient LO evidence in scoped plans."""
    if not professional_scope:
        return items
    cleaned: list[dict] = []
    for item in items:
        course = courses.get(item.get("course_id"))
        if course and curriculum_role(course, project_domains) == "general":
            evidence = aggregates.get(course.id, {})
            if float(evidence.get("max") or 0.0) < min_general_lo_evidence:
                continue
        cleaned.append(item)
    return cleaned


def is_project_domain_course(
    course: Course,
    *,
    education_level: str | None,
    professional_scope: bool,
    project_domains: Sequence[str],
    interdisciplinary_professional: bool,
    cyber_forensics_program: bool,
    epvo_professional_scope: bool,
    project_version_id: int,
    epvo_level_scope_allowed_ids: set[int],
    epvo_domain_index: Mapping[int, int],
    aggregates: Mapping[int, Mapping[str, object]],
    min_general_lo_evidence: float,
    education_level_allowed: Callable[[Course, str | None], bool],
    foreign_professional_title: Callable[[Course, Sequence[str]], bool],
    medicine_support_course: Callable[[Course, Sequence[str]], bool],
    course_domain_matches: Callable[[Course, Sequence[str]], bool],
    domain_label_matches: Callable[[str | None, Sequence[str]], bool],
    curriculum_role: Callable[[Course, Sequence[str]], str],
    scope_rank: Callable[[Course], int],
) -> bool:
    """Return whether a catalogue course is admissible for the project scope."""
    if not education_level_allowed(course, education_level):
        return False
    if professional_scope and foreign_professional_title(course, project_domains):
        return False
    course_code = str(course.course_id or "")
    project_confirmed_prefix = f"AI-CONFIRMED-{project_version_id}-"
    # Both declared domains are valid evidence for an interdisciplinary
    # programme.  The former non-IT-only gate silently rejected ICT courses
    # even when the project explicitly declared ICT as domain 2, which made
    # otherwise well-supported LOs appear uncovered at final verification.
    declared_domain_match = (
        course_domain_matches(course, project_domains)
        or domain_label_matches(course.domain, project_domains)
        or (
            is_information_technology_domain(course.domain)
            and any(is_information_technology_domain(domain) for domain in project_domains)
        )
    )
    secondary_domain_match = bool(
        interdisciplinary_professional and project_domains
        and (
            declared_domain_match
            or medicine_support_course(course, project_domains)
        )
    )
    evidence = aggregates.get(course.id, {})
    strong_lo_evidence = (
        course_code.startswith("EPVO-")
        and bool(evidence.get("professional_lo_codes"))
        and float(evidence.get("max") or 0.0) >= 0.8
    )
    # An explicit catalogue-domain match is authoritative secondary-domain
    # evidence. The narrower medicine-support heuristic is still useful for
    # ambiguous interdisciplinary titles, but must not discard clearly
    # labelled medical/health courses before quota repair sees them.
    if (
        interdisciplinary_professional
        and not secondary_domain_match
        and not declared_domain_match
    ):
        return False
    if course_code.startswith("AI-CONFIRMED-") and not course_code.startswith(project_confirmed_prefix):
        # Synthetic expert-confirmed replacements are project-local.
        return False
    if (
        course_code.startswith("EPVO-")
        and course.id not in epvo_level_scope_allowed_ids
        and not secondary_domain_match
        and not strong_lo_evidence
    ):
        return False
    if course.id not in epvo_domain_index and not (
        course_domain_matches(course, project_domains)
        or domain_label_matches(course.domain, project_domains)
        or strong_lo_evidence
    ):
        return False

    if professional_scope and not course_code.startswith("GOSO-KZ-"):
        if (
            epvo_professional_scope
            and course_code.startswith("EPVO-")
            and scope_rank(course) <= 0
            and float(evidence.get("max") or 0.0) < 0.55
            and not strong_lo_evidence
        ):
            return False
        # Scope membership alone is not enough for a non-regulatory course.
        # Exact selected-group evidence is an explicit catalogue admission
        # signal, while the final verifier still owns LO coverage.
        exact_scope = scope_rank(course) >= 3
        if (
            float(evidence.get("max") or 0.0) < 0.4
            and float(evidence.get("expert") or 0.0) < 0.5
            and not exact_scope
            and not course_code.startswith(project_confirmed_prefix)
        ):
            return False

    if cyber_forensics_program:
        return curriculum_role(course, project_domains) == "core"
    if professional_scope and curriculum_role(course, project_domains) == "general":
        if (
            float(evidence.get("max") or 0.0) < min_general_lo_evidence
            and not (
                scope_rank(course) >= 3
                and bool(evidence.get("professional_lo_codes"))
            )
        ):
            return False
    return True
