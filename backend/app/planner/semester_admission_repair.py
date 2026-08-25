from __future__ import annotations

import re
from typing import Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.course import Course, course_prerequisites
from app.models.embedding import MatchScore
from app.models.project import ProjectVersion
from app.planner.admission import (
    audit_final_course_admission as _audit_final_course_admission,
    credible_professional_lo_by_course as _credible_professional_lo_by_course,
    minimum_appropriate_semester as _minimum_appropriate_semester,
)
from app.planner.course_policy import (
    education_level_course_allowed as _education_level_course_allowed,
    project_domain_terms as _project_domain_terms,
)
from app.planner.scheduler_catalogue import unique_items_by_title as _unique_items_by_title
from app.planner.scheduler_domain_rules import (
    has_foreign_professional_title as _has_foreign_professional_title,
    is_it_medicine_support_course as _is_it_medicine_support_course,
)
from app.planner.scheduler_utils import title_key as _title_key
from app.planner.semester_load_repair import balance_semester_with_bridge
from app.planner.verifier import verify_curriculum_plan


def _repair_final_admission_misplacements(
    schedule: Dict[int, List[Dict]],
    candidate_pool: List[Dict],
    project_version: ProjectVersion,
    db: Session,
) -> Dict[int, List[Dict]]:
    """Replace an unplaceable late course with an equal-credit credible alternative."""
    normalized = {
        semester: [dict(item) for item in items]
        for semester, items in schedule.items()
    }
    constraints = project_version.project.constraints_json or {}
    num_semesters = int(constraints.get("total_semesters", len(normalized)) or len(normalized))
    seed_candidate_ids = {
        int(item["course_id"]) for item in candidate_pool
        if item.get("course_id") is not None
    }
    scored_candidate_ids = {
        int(course_id)
        for (course_id,) in db.query(MatchScore.course_id).filter(
            MatchScore.project_version_id == project_version.id
        ).distinct().all()
    }
    candidate_ids = seed_candidate_ids | scored_candidate_ids
    courses = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(candidate_ids or {-1})).all()
    }
    credible = _credible_professional_lo_by_course(project_version, candidate_ids, db)
    project_domains = _project_domain_terms(project_version, db)
    interdisciplinary = (
        str(constraints.get("program_type") or "standard").lower()
        in {"interdisciplinary", "joint"}
    )

    def domain_family(value: str | None) -> str:
        text = str(value or "").casefold()
        if any(marker in text for marker in (
            "информ", "computer", "software", "digital", "кибер",
        )) or re.search(r"\bit\b", text):
            return "it"
        if any(marker in text for marker in (
            "мед", "здрав", "health", "clinical", "medicine",
        )):
            return "medicine"
        return _title_key(text)

    project_families = {
        domain_family(domain) for domain in project_domains if domain
    }

    prerequisite_map: Dict[int, List[int]] = {}
    if candidate_ids:
        for row in db.execute(
            course_prerequisites.select().where(
                course_prerequisites.c.course_id.in_(candidate_ids)
            )
        ).fetchall():
            prerequisite_map.setdefault(int(row.course_id), []).append(
                int(row.prerequisite_id)
            )
    max_score_by_course = {
        int(course_id): float(max_score or 0.0)
        for course_id, max_score in db.query(
            MatchScore.course_id,
            func.max(MatchScore.score),
        ).filter(
            MatchScore.project_version_id == project_version.id,
        ).group_by(MatchScore.course_id).all()
    }
    expanded_pool = [dict(item) for item in candidate_pool]
    existing_pool_ids = {
        int(item["course_id"])
        for item in expanded_pool if item.get("course_id") is not None
    }
    for course_id, course in courses.items():
        course_code = str(course.course_id or "")
        family = domain_family(course.domain)
        if (
            course_id in existing_pool_ids
            or course_id not in credible
            or course_code.startswith("GOSO-KZ-")
            or not _education_level_course_allowed(
                course, constraints.get("education_level")
            )
            or (project_families and family not in project_families)
            or _has_foreign_professional_title(course, project_domains)
            or (
                interdisciplinary
                and not _is_it_medicine_support_course(course, project_domains)
            )
        ):
            continue
        expanded_pool.append({
            "course_id": course.id,
            "title": course.title,
            "domain": course.domain,
            "credits": int(course.credits or 5),
            "recommended_semester": course.recommended_semester,
            "prerequisites": prerequisite_map.get(course.id, []),
            "type": course.cycle_component or "elective",
            "admission_los": sorted(credible.get(course.id) or []),
            "admission_score": round(max_score_by_course.get(course.id, 0.0), 4),
            "selection_method": "final_admission_repository_candidate",
        })
    candidate_pool = _unique_items_by_title(expanded_pool)

    for _ in range(6):
        admission = _audit_final_course_admission(normalized, project_version, db)
        misplaced = next(
            (
                row for row in admission["violations"]
                if row.get("reason") == "too_early_for_complexity"
            ),
            None,
        )
        if not misplaced:
            break
        semester = int(misplaced["semester"])
        old_index = next(
            (
                index for index, item in enumerate(normalized[semester])
                if item.get("course_id") == misplaced.get("course_id")
            ),
            None,
        )
        if old_index is None:
            break
        old_item = normalized[semester][old_index]
        current_check = verify_curriculum_plan(normalized, project_version, db)
        current_admission_count = len(admission["violations"])
        current_misplacements = len(
            (current_check.get("pedagogical_audit") or {}).get(
                "semester_misplacements"
            ) or []
        )
        minimum_target = int(misplaced.get("minimum_semester") or semester + 1)
        loads = {
            value: sum(int(item.get("credits") or 0) for item in items)
            for value, items in normalized.items()
        }
        lower_load = int(constraints.get("max_credits_per_semester", 30) or 30) - 3
        upper_load = int(constraints.get("max_credits_per_semester", 30) or 30) + 3
        relocated = False
        for target_semester in range(minimum_target, num_semesters + 1):
            for target_index, displaced in enumerate(normalized[target_semester]):
                if (
                    displaced.get("course_id") is None
                    or displaced.get("regulatory_required")
                ):
                    continue
                displaced_course = courses.get(int(displaced["course_id"]))
                if (
                    displaced_course is None
                    or semester < _minimum_appropriate_semester(
                        displaced, displaced_course, num_semesters
                    )
                ):
                    continue
                old_credits = int(old_item.get("credits") or 0)
                displaced_credits = int(displaced.get("credits") or 0)
                source_load = loads[semester] - old_credits + displaced_credits
                target_load = (
                    loads[target_semester] - displaced_credits + old_credits
                )
                if not (
                    lower_load <= source_load <= upper_load
                    and lower_load <= target_load <= upper_load
                ):
                    continue
                trial = {
                    value: [dict(item) for item in items]
                    for value, items in normalized.items()
                }
                moved_late = dict(old_item)
                moved_late["selection_method"] = (
                    f"{old_item.get('selection_method') or 'selected'}"
                    "+final_semester_swap"
                )
                moved_early = dict(displaced)
                moved_early["selection_method"] = (
                    f"{displaced.get('selection_method') or 'selected'}"
                    "+final_semester_swap"
                )
                trial[semester][old_index] = moved_early
                trial[target_semester][target_index] = moved_late
                if not balance_semester_with_bridge(
                    trial,
                    semester,
                    displaced_credits - old_credits,
                ) or not balance_semester_with_bridge(
                    trial,
                    target_semester,
                    old_credits - displaced_credits,
                ):
                    continue
                checked = verify_curriculum_plan(trial, project_version, db)
                checked_admission = _audit_final_course_admission(
                    trial, project_version, db
                )
                checked_misplacements = len(
                    (checked.get("pedagogical_audit") or {}).get(
                        "semester_misplacements"
                    ) or []
                )
                if (
                    int(checked.get("hard_violation_count") or 0)
                    > int(current_check.get("hard_violation_count") or 0)
                    or len(checked_admission["violations"])
                    >= current_admission_count
                    or checked_misplacements > current_misplacements
                ):
                    continue
                normalized = trial
                relocated = True
                break
            if relocated:
                break
        if relocated:
            continue
        selected_ids = {
            int(item["course_id"])
            for items in normalized.values()
            for item in items if item.get("course_id") is not None
        }
        selected_titles = {
            _title_key(item.get("title"))
            for items in normalized.values()
            for item in items if item.get("title")
        }
        old_domain = str(old_item.get("domain") or "").casefold().strip()
        old_family = domain_family(old_domain)
        alternatives = [
            item for item in candidate_pool
            if item.get("course_id") is not None
            and int(item["course_id"]) not in selected_ids
            and int(item["course_id"]) in credible
            and _title_key(item.get("title")) not in selected_titles
            # A real EPVO course is atomic, but a one- or two-credit
            # difference can be absorbed by an existing 3--7 credit bridge.
            # Requiring exact equality here rejected valid early-semester
            # alternatives simply because the catalogue uses 3/4/5 credits.
            and abs(
                int(item.get("credits") or 0)
                - int(old_item.get("credits") or 0)
            ) <= 2
            and (
                not old_domain
                or old_family == domain_family(item.get("domain"))
            )
        ]
        alternatives.sort(key=lambda item: (
            -float(item.get("admission_score") or 0.0),
            int(item.get("recommended_semester") or 99),
            int(item.get("course_id") or 0),
        ))
        repaired = False
        for alternative in alternatives:
            course = courses.get(int(alternative["course_id"]))
            if not course or semester < _minimum_appropriate_semester(
                alternative, course, num_semesters
            ):
                continue
            prerequisites = {
                int(value) for value in (alternative.get("prerequisites") or [])
            }
            earlier_ids = {
                int(item["course_id"])
                for value, items in normalized.items() if value < semester
                for item in items if item.get("course_id") is not None
            }
            if not prerequisites.issubset(earlier_ids):
                continue
            trial = {
                value: [dict(item) for item in items]
                for value, items in normalized.items()
            }
            replacement = dict(alternative)
            replacement["selection_method"] = "final_admission_backtrack"
            trial[semester][old_index] = replacement
            credit_delta = (
                int(replacement.get("credits") or 0)
                - int(old_item.get("credits") or 0)
            )
            if not balance_semester_with_bridge(trial, semester, credit_delta):
                continue
            checked = verify_curriculum_plan(trial, project_version, db)
            checked_misplacements = len(
                (checked.get("pedagogical_audit") or {}).get("semester_misplacements") or []
            )
            if (
                int(checked.get("hard_violation_count") or 0)
                > int(current_check.get("hard_violation_count") or 0)
                or checked_misplacements >= current_misplacements
                or not _audit_final_course_admission(trial, project_version, db)["passed"]
            ):
                continue
            normalized = trial
            repaired = True
            break
        if not repaired:
            break
    return normalized
