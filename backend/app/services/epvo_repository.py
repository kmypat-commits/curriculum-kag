"""Approve project-scoped EPVO candidates into the active course repository.

Raw/normalized EPVO data stays in the EPVO layer.  The active course repository
receives only candidates that match the selected programme direction/group.
For interdisciplinary programmes the repository is filled from two scopes:
primary direction/group -> domain1, secondary direction/group -> domain2.
"""

from __future__ import annotations

import re

from sqlalchemy import String, cast, or_

from app.models.course import Course, CourseChunk
from app.models.epvo import EpvoDisciplineNormalized
from app.services.language import normalize_language


def _key(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _tokens(value: str | None) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w\-]+", (value or "").casefold(), flags=re.UNICODE)
        if len(token) > 2
    }


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, min(len(left), len(right)))


def epvo_row_text(row: EpvoDisciplineNormalized) -> str:
    content = row.content_json or {}
    return " ".join(str(part or "") for part in [
        row.canonical_title, row.title_ru, row.title_kk, row.title_en,
        content.get("description_ru"), content.get("description_kk"), content.get("description_en"),
        content.get("description"),
    ])


def _fallback_description(title: str, scope: str, language: str) -> str:
    scope_text = scope or "ЕПВО"
    if language == "kk":
        return f"{title} пәні {scope_text} бағыты бойынша білім беру бағдарламасын толықтыру үшін енгізіледі. Мазмұны негізгі ұғымдарды, практикалық тапсырмаларды және бағдарлама нәтижелерімен байланысын қамтиды."
    if language == "en":
        return f"The course {title} is included to support the {scope_text} educational programme scope. It covers core concepts, practical tasks, and links to programme learning outcomes."
    return f"Дисциплина «{title}» включена для усиления образовательной программы в области {scope_text}. Содержание охватывает ключевые понятия, практические задания и связь с результатами обучения программы."


def epvo_project_tokens(project_version) -> set[str]:
    return _tokens(" ".join([
        project_version.project.title or "",
        project_version.project.goal or "",
        project_version.project.domain1 or "",
        project_version.project.domain2 or "",
        " ".join(lo.lo_text or "" for lo in project_version.learning_outcomes),
    ]))


def education_level_prefixes(education_level: str | None) -> tuple[str, str] | None:
    """Return the authoritative EPVO direction/group prefixes for a degree level."""
    level = str(education_level or "").strip().lower()
    return {
        "bachelor": ("6B", "B"),
        "undergraduate": ("6B", "B"),
        "master": ("7M", "M"),
        "masters": ("7M", "M"),
        "magistracy": ("7M", "M"),
        "doctorate": ("8D", "D"),
        "doctoral": ("8D", "D"),
        "phd": ("8D", "D"),
    }.get(level)


def epvo_row_matches_education_level(
    row: EpvoDisciplineNormalized,
    education_level: str | None,
) -> bool:
    """A shared normalized course is eligible only if EPVO observed it at this level."""
    prefixes = education_level_prefixes(education_level)
    if not prefixes:
        return False
    direction_prefix, group_prefix = prefixes
    directions = [str(value or "").upper() for value in (row.direction_codes or [])]
    groups = [str(value or "").upper() for value in (row.group_codes or [])]
    return any(code.startswith(direction_prefix) for code in directions) or any(
        code.startswith(group_prefix) for code in groups
    )


def epvo_row_relevance_score(row: EpvoDisciplineNormalized, project_version, group_code: str = "", direction_code: str = "") -> float:
    """Data-driven EPVO relevance score, independent of hand-written blacklists."""
    constraints = project_version.project.constraints_json or {}
    if not epvo_row_matches_education_level(row, constraints.get("education_level")):
        return 0.0
    groups = {str(value or "").strip() for value in [group_code, constraints.get("group_code"), constraints.get("secondary_group_code")] if str(value or "").strip()}
    directions = {str(value or "").strip() for value in [direction_code, constraints.get("direction_code"), constraints.get("secondary_direction_code")] if str(value or "").strip()}
    row_groups = set(row.group_codes or [])
    row_directions = set(row.direction_codes or [])
    scope_score = 1.0 if groups & row_groups else 0.72 if directions & row_directions else 0.0
    semantic_score = _overlap(epvo_project_tokens(project_version), _tokens(epvo_row_text(row)))
    source_score = min(len(row.source_programs or []), 50) / 50
    metadata_score = 0.05 * bool(row.typical_credits) + 0.05 * bool(row.typical_semester)
    return round(scope_score * 0.62 + semantic_score * 0.28 + source_score * 0.05 + metadata_score, 4)


def epvo_row_is_relevant(row: EpvoDisciplineNormalized, project_version, group_code: str = "", direction_code: str = "", threshold: float = 0.52) -> bool:
    return epvo_row_relevance_score(row, project_version, group_code, direction_code) >= threshold


def approve_epvo_candidates(project_version, db, limit: int = 2000) -> dict:
    constraints = project_version.project.constraints_json or {}
    primary_group = str(constraints.get("group_code") or "")
    primary_direction = str(constraints.get("direction_code") or "")
    secondary_group = str(constraints.get("secondary_group_code") or "")
    secondary_direction = str(constraints.get("secondary_direction_code") or "")
    # Store and generate repository text using the same canonical language
    # codes as the API (kz/kaz/kazakh must resolve to kk).
    language = normalize_language(constraints.get("instruction_language"))
    program_type = str(constraints.get("program_type") or "standard").lower()

    scopes: list[tuple[str, str, int]] = [(primary_group, primary_direction, 0)]
    if program_type in {"interdisciplinary", "joint"} and (secondary_group or secondary_direction):
        scopes.append((secondary_group, secondary_direction, 1))
    scopes = [(group, direction, domain_index) for group, direction, domain_index in scopes if group or direction]
    if not scopes:
        return {"created": 0, "linked": 0, "scope": "none"}

    def scoped_rows(column, code: str, row_limit: int):
        return db.query(EpvoDisciplineNormalized).filter(
            cast(column, String).like(f'%"{code}"%')
        ).limit(row_limit).all()

    rows_with_source = []
    per_scope_limit = max(500, limit // max(1, len(scopes)))
    for group_code, direction_code, domain_index in scopes:
        rows = scoped_rows(EpvoDisciplineNormalized.group_codes, group_code, per_scope_limit * 5) if group_code else []
        scope_name = "group"
        if len(rows) < per_scope_limit and direction_code:
            existing_ids = {row.id for row in rows}
            rows.extend(
                row
                for row in scoped_rows(EpvoDisciplineNormalized.direction_codes, direction_code, per_scope_limit * 5)
                if row.id not in existing_ids
            )
            scope_name = "group+direction" if group_code else "direction"
        rows_with_source.extend(
            (row, group_code, direction_code, domain_index, scope_name)
            for row in rows
            if epvo_row_matches_education_level(row, constraints.get("education_level"))
        )

    deduped = {}
    for row, group_code, direction_code, domain_index, scope_name in rows_with_source:
        deduped.setdefault(row.id, (row, group_code, direction_code, domain_index, scope_name))
    rows_with_source = list(deduped.values())

    project_tokens = epvo_project_tokens(project_version)

    def row_rank(entry):
        row, group_code, direction_code, _domain_index, _scope_name = entry
        scope_score = (
            3 if group_code and group_code in (row.group_codes or [])
            else 2 if direction_code and direction_code in (row.direction_codes or [])
            else 0
        )
        semantic_score = _overlap(project_tokens, _tokens(epvo_row_text(row)))
        source_count = len(row.source_programs or [])
        return (
            scope_score,
            semantic_score,
            min(source_count, 50) / 50,
            bool(row.typical_credits),
            bool(row.typical_semester),
        )

    rows_with_source.sort(key=row_rank, reverse=True)

    row_ids = [int(entry[0].id) for entry in rows_with_source]
    approved_course_ids = {
        int(entry[0].approved_course_id)
        for entry in rows_with_source
        if entry[0].approved_course_id is not None
    }
    existing_conditions = [Course.course_id.in_([f"EPVO-{row_id}" for row_id in row_ids] or [""])]
    if approved_course_ids:
        existing_conditions.append(Course.id.in_(approved_course_ids))
    # Exact-title fallback is only needed for not-yet-linked legacy rows.
    unlinked_titles = {
        title.strip()
        for row, *_rest in rows_with_source
        if row.approved_course_id is None
        for title in (row.title_ru, row.title_kk, row.title_en, row.canonical_title)
        if title and title.strip()
    }
    if unlinked_titles:
        existing_conditions.append(Course.title.in_(unlinked_titles))
    existing_courses = db.query(Course).filter(or_(*existing_conditions)).all()
    by_title = {_key(course.title): course for course in existing_courses if course.title}
    by_code = {course.course_id: course for course in existing_courses}
    translations, created, linked = {}, 0, 0
    domains = [project_version.project.domain1, project_version.project.domain2]
    domain_tokens = [_tokens(value) for value in domains]
    approved_courses: list[Course] = []
    source_counts: dict[str, int] = {}

    overall_limit = limit * max(1, len(scopes))
    for row, group_code, direction_code, source_domain_index, scope_name in rows_with_source:
        if created + linked >= overall_limit:
            break
        if not epvo_row_is_relevant(row, project_version, group_code, direction_code):
            continue
        content = row.content_json or {}
        titles = {"ru": row.title_ru, "kk": row.title_kk, "en": row.title_en}
        descriptions = {
            "ru": content.get("description_ru"),
            "kk": content.get("description_kk"),
            "en": content.get("description_en"),
        }
        title = titles.get("kk" if language in {"kk", "kz"} else language) or row.title_ru or row.title_en or row.canonical_title
        if not title or len(title.strip()) < 3:
            continue
        scope_label = group_code or direction_code or scope_name
        for lang in ("ru", "kk", "en"):
            descriptions[lang] = descriptions.get(lang) or _fallback_description(
                titles.get(lang) or title,
                scope_label,
                lang,
            )

        course = by_code.get(f"EPVO-{row.id}") or by_title.get(_key(title)) or by_title.get(_key(row.canonical_title))
        if course is None:
            credits = int(round(float(row.typical_credits or 5)))
            credits = min(10, max(2, credits))
            suffix = "kk" if language in {"kk", "kz"} else language
            description = (
                content.get(f"description_{suffix}")
                or descriptions.get(suffix)
                or _fallback_description(title, scope_label, suffix)
            )
            title_tokens = _tokens(title) | _tokens(description)
            domain_scores = [_overlap(tokens, title_tokens) for tokens in domain_tokens]
            fallback_domain_index = 0 if not domain_scores or domain_scores[0] >= domain_scores[-1] else 1
            domain_index = source_domain_index if source_domain_index < len(domains) else fallback_domain_index
            course = Course(
                course_id=f"EPVO-{row.id}",
                title=title.strip(),
                domain=domains[domain_index] or domains[0] or "general",
                credits=credits,
                recommended_semester=min(
                    int(constraints.get("total_semesters", 8)),
                    max(1, int(row.typical_semester or 1)),
                ),
                description=description,
                topics=[],
                learning_outcomes=[],
                assessment_methods=["экспертная оценка", "проектное задание"],
                language=language,
                cycle_component="вузовский компонент" if created % 3 else "компонент по выбору",
            )
            db.add(course)
            db.flush()
            db.add(CourseChunk(course_id=course.id, chunk_type="description", chunk_text=description, chunk_index=0))
            by_code[course.course_id] = course
            by_title[_key(course.title)] = course
            created += 1
        else:
            linked += 1

        row.status = "approved"
        row.approved_course_id = course.id
        translations[course.id] = {
            "title": titles,
            "description": descriptions,
            "review_status": "verified_epvo",
            "source": "epvo_normalized_repository",
        }
        approved_courses.append(course)
        source_key = group_code or direction_code or scope_name
        source_counts[source_key] = source_counts.get(source_key, 0) + 1

    _assign_epvo_prerequisites(approved_courses)
    db.flush()
    scope = "multi-scope" if len(scopes) > 1 else "group+direction" if primary_group and primary_direction else "group" if primary_group else "direction"
    return {
        "created": created,
        "linked": linked,
        "scope": scope,
        "group_code": primary_group,
        "direction_code": primary_direction,
        "secondary_group_code": secondary_group,
        "secondary_direction_code": secondary_direction,
        "source_counts": source_counts,
        "translations": translations,
    }


def _assign_epvo_prerequisites(courses: list[Course], replace_existing: bool = False) -> int:
    """Assign only explainable prerequisites from earlier EPVO semesters.

    Semester order alone is not evidence: an arbitrary earlier course must not
    become a prerequisite.  A link is created only when the course texts share
    subject terms, with a small preference for explicit foundation courses.
    """
    exempt_marker = "__prerequisite_exempt__"
    stopwords = {
        "дисциплина", "изучение", "основные", "современные", "методы",
        "технологии", "системы", "модуль", "course", "methods", "systems",
        "technology", "technologies", "introduction", "введение", "основы",
    }

    def subject_tokens(course: Course) -> set[str]:
        return _tokens(" ".join((course.title or "", course.description or ""))) - stopwords

    def is_foundation(course: Course) -> bool:
        title = _key(course.title)
        return title.startswith(("основы ", "введение ", "fundamentals ", "introduction "))

    by_domain: dict[str, list[Course]] = {}
    for course in courses:
        if replace_existing:
            course.prerequisites = []
        by_domain.setdefault(course.domain or "general", []).append(course)

    updated = 0
    for domain_courses in by_domain.values():
        ordered = sorted(
            domain_courses,
            key=lambda course: (course.recommended_semester or 1, course.credits or 5, course.id or 0),
        )
        for course in ordered:
            semester = int(course.recommended_semester or 1)
            if semester <= 1 or course.prerequisites or exempt_marker in set(course.topics or []):
                continue
            target_tokens = subject_tokens(course)
            ranked = []
            for candidate in ordered:
                if candidate.id == course.id or int(candidate.recommended_semester or 1) >= semester:
                    continue
                shared = target_tokens & subject_tokens(candidate)
                if len(shared) < 2:
                    continue
                score = len(shared) + (1.0 if is_foundation(candidate) else 0.0)
                score += 0.2 * int(candidate.recommended_semester or 1)
                ranked.append((score, candidate))
            if ranked:
                ranked.sort(key=lambda pair: (pair[0], pair[1].id or 0), reverse=True)
                course.prerequisites = [candidate for _, candidate in ranked[:2]]
                updated += 1
    return updated
