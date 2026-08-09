from __future__ import annotations

from itertools import combinations
import re
from statistics import median
from typing import Dict, List

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.bridge_module import BridgeModule
from app.models.course import Course, course_prerequisites
from app.models.embedding import MatchScore
from app.models.epvo import EpvoDisciplineNormalized
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
from app.planner.scheduler_utils import (
    move_item as _move_item,
    swap_items as _swap_items,
    title_key as _title_key,
)
from app.planner.semester_rules import (
    complexity_min_semester as _complexity_min_semester,
    foundation_max_semester as _foundation_max_semester,
    late_stage_min_semester as _late_stage_min_semester,
    minimum_appropriate_semester as _item_minimum_appropriate_semester,
)
from app.planner.verifier import verify_curriculum_plan
from app.services.epvo_repository import epvo_row_matches_education_level


def _repair_semester_appropriateness(
    schedule: Dict[int, List[Dict]],
    num_semesters: int,
    nominal_load: int,
    db: Session,
) -> Dict[int, List[Dict]]:
    """Repair semantic semester bounds without breaking load/prerequisites."""
    course_ids = {
        int(item["course_id"])
        for items in schedule.values()
        for item in items
        if item.get("course_id") is not None
    }
    courses = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()
    }
    lower_load, upper_load = nominal_load - 3, nominal_load + 3

    def bounds(item: Dict) -> tuple[int, int]:
        if item.get("regulatory_required"):
            semester = max(1, min(num_semesters, int(item.get("recommended_semester") or 1)))
            return semester, semester
        course = courses.get(item.get("course_id"))
        if not course:
            return 1, num_semesters
        recommended = int(item.get("recommended_semester") or course.recommended_semester or 0)
        semantic_upper = _foundation_max_semester(course.title, num_semesters)
        if item.get("prerequisites"):
            # "Основы" can name a domain foundation built on earlier general
            # prerequisites (for example engineering calculations after
            # mathematics).  In that case the source semester and graph are
            # stronger evidence than the lexical prefix alone. A late source
            # recommendation by itself is not enough: EPVO often contains the
            # same introductory course in different programme semesters.
            semantic_upper = max(semantic_upper, min(num_semesters, recommended + 2))
        recommended_lower = max(1, recommended - 1) if recommended else 1
        # A late semester copied from one source programme must not turn an
        # explicitly introductory course into a capstone. Semantic foundation
        # bounds are authoritative when the two signals conflict.
        if recommended_lower > semantic_upper:
            recommended_lower = 1
        lower = max(
            1,
            _late_stage_min_semester(course.title, num_semesters),
            _complexity_min_semester({
                "title": course.title,
                "domain": item.get("domain") or course.domain,
                "type": item.get("type") or course.cycle_component,
            }, num_semesters),
            recommended_lower,
        )
        upper = max(lower, semantic_upper)
        return lower, min(num_semesters, upper)

    def prerequisites_valid(candidate: Dict[int, List[Dict]]) -> bool:
        semester_by_course = {
            item.get("course_id"): semester
            for semester, items in candidate.items()
            for item in items
            if item.get("course_id") is not None
        }
        return all(
            semester_by_course.get(prerequisite_id, 0) < semester
            for semester, items in candidate.items()
            for item in items
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in semester_by_course
        )

    for _ in range(2):
        changed = False
        loads = {
            semester: sum(int(item.get("credits") or 0) for item in items)
            for semester, items in schedule.items()
        }
        misplaced = [
            (semester, item, *bounds(item))
            for semester, items in schedule.items()
            for item in list(items)
            if item.get("course_id") is not None
            and not (bounds(item)[0] <= semester <= bounds(item)[1])
        ]
        for current, item, lower, upper in misplaced:
            credits = int(item.get("credits") or 0)
            targets = sorted(
                range(lower, upper + 1),
                key=lambda semester: (abs(semester - current), loads.get(semester, 0)),
            )
            repaired = False
            for target in targets:
                if target == current:
                    continue
                if (
                    loads[current] - credits >= lower_load
                    and loads[target] + credits <= upper_load
                ):
                    candidate = {semester: list(items) for semester, items in schedule.items()}
                    if not _move_item(candidate, current, target, item):
                        continue
                    if prerequisites_valid(candidate):
                        schedule = candidate
                        loads[current] -= credits
                        loads[target] += credits
                        repaired = changed = True
                        break
                for other in list(schedule[target]):
                    if other.get("course_id") is None:
                        continue
                    other_credits = int(other.get("credits") or 0)
                    new_current_load = loads[current] - credits + other_credits
                    new_target_load = loads[target] - other_credits + credits
                    if not (
                        lower_load <= new_current_load <= upper_load
                        and lower_load <= new_target_load <= upper_load
                    ):
                        continue
                    other_lower, other_upper = bounds(other)
                    if not (other_lower <= current <= other_upper):
                        continue
                    candidate = {semester: list(items) for semester, items in schedule.items()}
                    if not _swap_items(candidate, current, item, target, other):
                        continue
                    if prerequisites_valid(candidate):
                        schedule = candidate
                        loads[current] = new_current_load
                        loads[target] = new_target_load
                        repaired = changed = True
                        break
                if repaired:
                    break
        if not changed:
            break

    # A one-for-one swap is sometimes impossible when every early semester is
    # full of 3-credit courses while the misplaced foundation has 5 credits.
    # Try a bounded three-way rotation (late -> early -> middle -> late).  This
    # preserves semester loads, semantic bounds and every prerequisite edge.
    for _ in range(3):
        loads = {
            semester: sum(int(item.get("credits") or 0) for item in items)
            for semester, items in schedule.items()
        }
        unresolved = [
            (semester, item, *bounds(item))
            for semester, items in schedule.items()
            for item in list(items)
            if item.get("course_id") is not None
            and not (bounds(item)[0] <= semester <= bounds(item)[1])
        ]
        rotated = False
        for current, item, lower, upper in unresolved:
            item_credits = int(item.get("credits") or 0)
            for target in range(lower, upper + 1):
                if target == current:
                    continue
                for displaced in list(schedule[target]):
                    if displaced.get("regulatory_required") or displaced.get("course_id") is None:
                        continue
                    displaced_credits = int(displaced.get("credits") or 0)
                    for receiver in schedule:
                        if receiver in {current, target}:
                            continue
                        displaced_lower, displaced_upper = bounds(displaced)
                        if not (displaced_lower <= receiver <= displaced_upper):
                            continue
                        for third in list(schedule[receiver]):
                            if third.get("regulatory_required") or third.get("course_id") is None:
                                continue
                            third_lower, third_upper = bounds(third)
                            if not (third_lower <= current <= third_upper):
                                continue
                            third_credits = int(third.get("credits") or 0)
                            candidate_loads = {
                                **loads,
                                current: loads[current] - item_credits + third_credits,
                                target: loads[target] - displaced_credits + item_credits,
                                receiver: loads[receiver] - third_credits + displaced_credits,
                            }
                            if any(
                                not lower_load <= candidate_loads[semester] <= upper_load
                                for semester in (current, target, receiver)
                            ):
                                continue
                            candidate = {semester: list(items) for semester, items in schedule.items()}
                            if not _move_item(candidate, current, target, item):
                                continue
                            if not _move_item(candidate, target, receiver, displaced):
                                continue
                            if not _move_item(candidate, receiver, current, third):
                                continue
                            if not prerequisites_valid(candidate):
                                continue
                            schedule = candidate
                            rotated = True
                            break
                        if rotated:
                            break
                    if rotated:
                        break
                if rotated:
                    break
            if rotated:
                break
        if not rotated:
            break
    return schedule
def _repair_final_domain_quotas(
    schedule: Dict[int, List[Dict]],
    candidate_pool: List[Dict],
    project_version: ProjectVersion,
    db: Session,
) -> Dict[int, List[Dict]]:
    """Restore domain quotas after late bridge/LO repairs.

    Earlier selection already has a broad, evidence-filtered candidate pool,
    but later exact-credit and LO repairs can replace a subject course with a
    shared bridge. This bounded equal-credit swap accepts a candidate only
    when the verifier reports a strictly smaller domain deficit and no new
    non-domain hard violation.
    """
    constraints = project_version.project.constraints_json or {}
    if (
        str(constraints.get("program_type") or "standard").lower()
        not in {"interdisciplinary", "joint"}
    ):
        return schedule
    project_domains = [
        str(project_version.project.domain1 or "").casefold().strip(),
        str(project_version.project.domain2 or "").casefold().strip(),
    ]

    def domain_index(item: Dict) -> int | None:
        item_domain = str(item.get("domain") or "").casefold().strip()
        for index, domain in enumerate(project_domains):
            if domain and (domain in item_domain or item_domain in domain):
                return index
        return None

    def domain_deficit(verification: Dict) -> float:
        return sum(
            max(
                0.0,
                float(row.get("required_credits") or 0.0)
                - float(row.get("tolerance_credits") or 0.0)
                - float(row.get("actual_credits") or 0.0),
            )
            for row in (verification.get("domain_quota_violations") or [])
        )

    def non_domain_hard_count(verification: Dict) -> int:
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

    normalized = {
        semester: [dict(item) for item in items]
        for semester, items in schedule.items()
    }
    candidate_ids = {
        int(item["course_id"])
        for item in candidate_pool
        if item.get("course_id") is not None
    }
    credible_candidates = _credible_professional_lo_by_course(
        project_version, candidate_ids, db
    )
    candidate_courses = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(candidate_ids or {-1})).all()
    }
    candidates = [
        dict(item) for item in _unique_items_by_title(candidate_pool)
        if (
            item.get("course_id") is not None
            and domain_index(item) in (0, 1)
            and int(item["course_id"]) in credible_candidates
        )
    ]
    candidates.sort(
        key=lambda item: (
            float(item.get("admission_score") or 0.0),
            -len(item.get("prerequisites") or []),
            -int(item.get("recommended_semester") or 99),
        ),
        reverse=True,
    )

    for _ in range(max(8, len(candidates))):
        current = verify_curriculum_plan(normalized, project_version, db)
        current_deficit = domain_deficit(current)
        if current_deficit <= 1e-9:
            break
        missing_domains = {
            int(row.get("domain_index") or 0) - 1
            for row in (current.get("domain_quota_violations") or [])
        }
        selected_ids = {
            int(item["course_id"])
            for items in normalized.values()
            for item in items
            if item.get("course_id") is not None
        }
        selected_titles = {
            _title_key(item.get("title"))
            for items in normalized.values()
            for item in items
            if item.get("title")
        }
        protected_ids = {
            int(prerequisite_id)
            for items in normalized.values()
            for item in items
            for prerequisite_id in (item.get("prerequisites") or [])
            if prerequisite_id in selected_ids
        }
        improved = False
        for candidate in candidates:
            candidate_id = int(candidate["course_id"])
            candidate_domain = domain_index(candidate)
            if (
                candidate_domain not in missing_domains
                or candidate_id in selected_ids
                or _title_key(candidate.get("title")) in selected_titles
            ):
                continue
            prerequisites = {
                int(value) for value in (candidate.get("prerequisites") or [])
            }
            if not prerequisites.issubset(selected_ids):
                continue
            candidate_credits = int(candidate.get("credits") or 0)
            replaceable = [
                (semester, index, item)
                for semester, items in normalized.items()
                for index, item in enumerate(items)
                if not item.get("regulatory_required")
                and not item.get("competency_required")
                and int(item.get("credits") or 0) == candidate_credits
                and item.get("course_id") not in protected_ids
                and domain_index(item) != candidate_domain
                and item.get("course_id") not in prerequisites
            ]
            replaceable.sort(
                key=lambda row: (
                    0 if row[2].get("bridge_module_id") is not None else 1,
                    float(row[2].get("admission_score") or 0.0),
                    -row[0],
                )
            )
            for semester, index, old_item in replaceable:
                candidate_course = candidate_courses.get(candidate_id)
                if (
                    candidate_course
                    and semester < _minimum_appropriate_semester(
                        candidate, candidate_course, int(constraints.get("total_semesters", len(normalized)) or len(normalized))
                    )
                ):
                    continue
                trial = {
                    value: [dict(item) for item in items]
                    for value, items in normalized.items()
                }
                replacement = dict(candidate)
                replacement["selection_method"] = "final_domain_quota_repair"
                trial[semester][index] = replacement
                trial = _repair_semester_appropriateness(
                    trial,
                    int(constraints.get("total_semesters", len(trial)) or len(trial)),
                    int(constraints.get("max_credits_per_semester", 30) or 30),
                    db,
                )
                checked = verify_curriculum_plan(trial, project_version, db)
                if (
                    non_domain_hard_count(checked) <= non_domain_hard_count(current)
                    and domain_deficit(checked) + 1e-9 < current_deficit
                ):
                    normalized = trial
                    improved = True
                    break
            if improved:
                break
        if not improved:
            eligible = [
                candidate
                for candidate in candidates
                if domain_index(candidate) in missing_domains
                and int(candidate["course_id"]) not in selected_ids
                and _title_key(candidate.get("title")) not in selected_titles
                and {
                    int(value) for value in (candidate.get("prerequisites") or [])
                }.issubset(selected_ids)
            ][:40]
            replaceable = [
                (semester, index, item)
                for semester, items in normalized.items()
                for index, item in enumerate(items)
                if not item.get("regulatory_required")
                and not item.get("competency_required")
                and item.get("course_id") not in protected_ids
                and domain_index(item) not in missing_domains
            ]
            replacement_groups: Dict[int, List[tuple]] = {}
            for size in (1, 2):
                for group in combinations(replaceable, size):
                    credits = sum(int(row[2].get("credits") or 0) for row in group)
                    replacement_groups.setdefault(credits, []).append(group)
            for candidate_group in combinations(eligible, 2):
                candidate_ids = {int(item["course_id"]) for item in candidate_group}
                if any(
                    set(int(value) for value in (item.get("prerequisites") or []))
                    & candidate_ids
                    for item in candidate_group
                ):
                    continue
                credits = sum(int(item.get("credits") or 0) for item in candidate_group)
                groups = replacement_groups.get(credits) or []
                for replacement_group in groups:
                    trial = {
                        value: [dict(item) for item in items]
                        for value, items in normalized.items()
                    }
                    target_semesters = [row[0] for row in replacement_group]
                    for semester, index, _item in sorted(
                        replacement_group,
                        key=lambda row: (row[0], row[1]),
                        reverse=True,
                    ):
                        del trial[semester][index]
                    for index, candidate in enumerate(candidate_group):
                        replacement = dict(candidate)
                        replacement["selection_method"] = "final_domain_quota_group_repair"
                        target = target_semesters[min(index, len(target_semesters) - 1)]
                        candidate_course = candidate_courses.get(int(candidate["course_id"]))
                        if (
                            candidate_course
                            and target < _minimum_appropriate_semester(
                                candidate,
                                candidate_course,
                                int(constraints.get("total_semesters", len(normalized)) or len(normalized)),
                            )
                        ):
                            break
                        trial[target].append(replacement)
                    else:
                        candidate_course = None
                    if candidate_course is not None:
                        continue
                    trial = _repair_semester_appropriateness(
                        trial,
                        int(constraints.get("total_semesters", len(trial)) or len(trial)),
                        int(constraints.get("max_credits_per_semester", 30) or 30),
                        db,
                    )
                    checked = verify_curriculum_plan(trial, project_version, db)
                    if (
                        non_domain_hard_count(checked) <= non_domain_hard_count(current)
                        and domain_deficit(checked) + 1e-9 < current_deficit
                    ):
                        normalized = trial
                        improved = True
                        break
                if improved:
                    break
        if not improved:
            break
    return normalized
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
            and int(item.get("credits") or 0) == int(old_item.get("credits") or 0)
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
def _apply_scoped_epvo_semesters(
    items: List[Dict], project_version: ProjectVersion, db: Session
) -> List[Dict]:
    """Attach the typical semester from the selected EPVO scope when known."""
    constraints = project_version.project.constraints_json or {}
    groups = {
        str(value).strip()
        for value in (constraints.get("group_code"), constraints.get("secondary_group_code"))
        if str(value or "").strip()
    }
    directions = {
        str(value).strip()
        for value in (constraints.get("direction_code"), constraints.get("secondary_direction_code"))
        if str(value or "").strip()
    }
    max_semesters = int(constraints.get("total_semesters") or 0)
    local_course_ids = {
        int(item["course_id"])
        for item in items
        if item.get("course_id") is not None
        and not item.get("regulatory_required")
        and item.get("bridge_module_id") is None
    }
    local_to_epvo: Dict[int, int] = {}
    if local_course_ids:
        for course in db.query(Course).filter(Course.id.in_(local_course_ids)).all():
            code = str(course.course_id or "")
            if code.startswith("EPVO-"):
                try:
                    local_to_epvo[int(course.id)] = int(code.split("-", 1)[1])
                except (TypeError, ValueError):
                    continue
    # EPVO repository cards use ``EPVO-<normalized row id>`` as their stable
    # public code.  Older imported cards may instead use approved_course_id.
    # Query both keys so scoped semester evidence is never silently skipped.
    course_ids = set(local_to_epvo.values())
    scoped_values: Dict[int, List[int]] = {}
    if course_ids and (groups or directions):
        rows = db.query(EpvoDisciplineNormalized).filter(
            or_(
                EpvoDisciplineNormalized.id.in_(course_ids),
                EpvoDisciplineNormalized.approved_course_id.in_(course_ids),
            )
        ).all()
        for row in rows:
            if not epvo_row_matches_education_level(row, constraints.get("education_level")):
                continue
            if not (groups.intersection(row.group_codes or []) or directions.intersection(row.direction_codes or [])):
                continue
            value = int(row.typical_semester or 0)
            if 1 <= value and (not max_semesters or value <= max_semesters):
                key = int(row.id) if int(row.id) in course_ids else int(row.approved_course_id)
                scoped_values.setdefault(key, []).append(value)
    for item in items:
        local_id = int(item["course_id"]) if item.get("course_id") is not None else None
        epvo_id = local_to_epvo.get(local_id, local_id) if local_id is not None else None
        values = scoped_values.get(epvo_id, []) if epvo_id is not None else []
        # A scoped EPVO median (selected direction/group and education level)
        # is more informative than the global catalogue median.  Preserve it
        # when the caller has already attached one; use the global value only
        # as a fallback for unscoped candidates.
        if values:
            # The selected EPVO direction/group is stronger evidence than a
            # recommendation copied from an unrelated catalogue row.  Mark
            # the origin so the generic scheduler cannot overwrite it with a
            # global median on the next pass.
            item["recommended_semester"] = int(round(median(values)))
            item["_scoped_epvo_semester"] = True
    return items
def schedule_courses(courses: List[Dict], num_semesters: int, nominal_load: int, db: Session) -> Dict[int, List[Dict]]:
    courses = _unique_items_by_title(courses)
    # EPVO may contain several historical rows for one canonical course.  A
    # single row's recommended semester is therefore unstable.  Before
    # placement, use the median of available EPVO semesters for each real
    # course.  Regulatory GOSO and bridge items keep their explicit semester.
    local_course_ids = {
        int(item["course_id"])
        for item in courses
        if item.get("course_id") is not None
        and not item.get("regulatory_required")
        and item.get("bridge_module_id") is None
    }
    local_to_epvo: Dict[int, int] = {}
    if local_course_ids:
        for course in db.query(Course).filter(Course.id.in_(local_course_ids)).all():
            code = str(course.course_id or "")
            if code.startswith("EPVO-"):
                try:
                    local_to_epvo[int(course.id)] = int(code.split("-", 1)[1])
                except (TypeError, ValueError):
                    continue
    epvo_course_ids = set(local_to_epvo.values())
    semester_values: Dict[int, List[int]] = {}
    if epvo_course_ids:
        rows = db.query(EpvoDisciplineNormalized).filter(
            or_(
                EpvoDisciplineNormalized.id.in_(epvo_course_ids),
                EpvoDisciplineNormalized.approved_course_id.in_(epvo_course_ids),
            )
        ).all()
        for row in rows:
            value = int(row.typical_semester or 0)
            if 1 <= value <= num_semesters:
                key = int(row.id) if int(row.id) in epvo_course_ids else int(row.approved_course_id)
                semester_values.setdefault(key, []).append(value)
    for item in courses:
        course_id = item.get("course_id")
        local_id = int(course_id) if course_id is not None else None
        epvo_id = local_to_epvo.get(local_id, local_id) if local_id is not None else None
        values = semester_values.get(epvo_id, []) if epvo_id is not None else []
        if values and not item.get("_scoped_epvo_semester"):
            item["recommended_semester"] = int(round(median(values)))
    schedule = {semester: [] for semester in range(1, num_semesters + 1)}
    loads = {semester: 0 for semester in schedule}
    lower, upper = max(0, nominal_load - 3), nominal_load + 3
    course_map = {item.get("course_id"): item for item in courses if item.get("course_id") is not None}
    depth_cache = {}
    def depth(cid, path=None):
        if cid in depth_cache: return depth_cache[cid]
        path = path or set()
        if cid in path: return num_semesters
        item = course_map.get(cid)
        if not item: return 0
        parents = [pid for pid in item.get("prerequisites", []) if pid in course_map]
        value = 0 if not parents else 1 + max(depth(pid, path | {cid}) for pid in parents)
        depth_cache[cid] = value; return value
    required_ids = {prerequisite for item in courses for prerequisite in (item.get("prerequisites", []) or [])}
    dependents = {}
    for item in courses:
        for prerequisite in item.get("prerequisites", []) or []:
            if prerequisite in course_map:
                dependents.setdefault(prerequisite, []).append(item.get("course_id"))
    tail_cache = {}
    def tail_depth(cid, path=None):
        if cid in tail_cache: return tail_cache[cid]
        path = path or set()
        if cid in path: return 0
        children = [child for child in dependents.get(cid, []) if child in course_map]
        value = 0 if not children else 1 + max(tail_depth(child, path | {cid}) for child in children)
        tail_cache[cid] = value
        return value
    ordered = sorted(courses, key=lambda item: (depth(item.get("course_id")) if item.get("course_id") else 0, 0 if item.get("course_id") in required_ids else 1, -(item.get("credits") or 0)))
    placed = {}
    for item in ordered:
        prereq_semesters = [placed[p] for p in item.get("prerequisites", []) if p in placed]
        earliest = min(max(prereq_semesters, default=0) + 1, num_semesters)
        regulatory_semester = (
            int(item.get("recommended_semester") or 1)
            if item.get("regulatory_required") and str(item.get("type") or "").startswith("goso_")
            else _late_stage_min_semester(item.get("title"), num_semesters)
        )
        earliest = max(earliest, min(num_semesters, regulatory_semester))
        earliest = max(earliest, _complexity_min_semester(item, num_semesters))
        recommended = item.get("variant_preferred_semester") or item.get("recommended_semester")
        semantic_upper = _foundation_max_semester(item.get("title"), num_semesters)
        if item.get("prerequisites") and recommended:
            semantic_upper = max(
                semantic_upper, min(num_semesters, int(recommended) + 2)
            )
        recommended_lower = max(1, int(recommended) - 1) if recommended else 1
        if recommended_lower <= semantic_upper:
            earliest = max(earliest, recommended_lower)
        cid = item.get("course_id")
        bridge_id = item.get("bridge_module_id")
        if bridge_id is not None:
            bridge = db.query(BridgeModule).filter(BridgeModule.id == bridge_id).first()
            if bridge and (bridge.course_id or "").startswith(("CORE_BRIDGE_", "SECONDARY_")):
                recommended_bridge_semester = int(bridge.recommended_semester or item.get("recommended_semester") or 1)
                item["recommended_semester"] = recommended_bridge_semester
                item["latest_semester"] = min(
                    num_semesters,
                    recommended_bridge_semester
                    + (2 if (bridge.course_id or "").startswith("CORE_BRIDGE_") else 1),
                )
        latest = max(earliest, min(
            int(item.get("latest_semester") or num_semesters),
            semantic_upper,
            num_semesters - (tail_depth(cid) if cid is not None else 0),
        ))
        item["latest_semester"] = latest
        candidates = list(range(earliest, latest + 1))
        valid = [s for s in candidates if loads[s] + (item.get("credits") or 0) <= upper]
        pool = valid or candidates
        target = min(
            pool,
            key=lambda semester: (
                abs(semester - int(recommended)) if recommended else 0,
                semester,
            ),
        )
        schedule[target].append(item); loads[target] += item.get("credits") or 0
        if item.get("course_id") is not None: placed[item["course_id"]] = target
    changed = True
    while changed:
        changed = False
        semester_by_course = {item["course_id"]: semester for semester, items in schedule.items() for item in items if item.get("course_id") is not None}
        for target_semester in [s for s in schedule if loads[s] < lower]:
            for donor_semester in sorted(schedule, key=lambda s: loads[s], reverse=True):
                if donor_semester == target_semester: continue
                for item in list(schedule[donor_semester]):
                    credits = item.get("credits") or 0
                    # Do not use a scoped EPVO course as a generic load
                    # shuttle: moving it away from its evidence-backed
                    # semester is exactly the failure measured by the
                    # external alignment audit.  Unscoped and bridge items
                    # remain available for balancing below.
                    if item.get("_scoped_epvo_semester"):
                        recommended_semester = int(item.get("recommended_semester") or 0)
                        if recommended_semester and target_semester != recommended_semester:
                            continue
                    if item.get("regulatory_required") and target_semester != int(item.get("recommended_semester") or donor_semester):
                        continue
                    if target_semester < _item_minimum_appropriate_semester(
                        item, num_semesters
                    ):
                        continue
                    if loads[donor_semester] - credits < lower or loads[target_semester] + credits > upper: continue
                    parent_semesters = [semester_by_course.get(p, 0) for p in item.get("prerequisites", []) or []]
                    child_semesters = [semester_by_course.get(d, num_semesters + 1) for d in dependents.get(item.get("course_id"), [])]
                    if parent_semesters and max(parent_semesters) >= target_semester: continue
                    if child_semesters and min(child_semesters) <= target_semester: continue
                    if not _move_item(schedule, donor_semester, target_semester, item):
                        continue
                    loads[donor_semester] -= credits; loads[target_semester] += credits
                    changed = True; break
                if changed: break
            if changed: break
    # A balanced load can still contain an avoidable semester inversion: an
    # EPVO-scoped course recommended for an early term may sit late while a
    # later course occupies its slot. Repair this with bounded-credit swaps so
    # loads remain within the configured tolerance. Every proposed swap is checked against both
    # prerequisite and dependent edges as well as semantic semester bounds.
    def improve_scoped_semester_alignment() -> None:
        def semester_map() -> Dict[int, int]:
            return {
                int(row.get("course_id")): int(semester)
                for semester, rows in schedule.items()
                for row in rows
                if row.get("course_id") is not None
            }

        def valid_assignment(item: Dict, target: int, mapping: Dict[int, int]) -> bool:
            if target < _item_minimum_appropriate_semester(item, num_semesters):
                return False
            latest = int(item.get("latest_semester") or num_semesters)
            if target > min(num_semesters, latest):
                return False
            course_id = item.get("course_id")
            if course_id is None:
                return True
            parents = [mapping.get(int(pid)) for pid in item.get("prerequisites", []) or []]
            if any(value is not None and value >= target for value in parents):
                return False
            children = [mapping.get(int(cid)) for cid in dependents.get(course_id, [])]
            if any(value is not None and value <= target for value in children):
                return False
            return True

        for _ in range(4):
            mapping = semester_map()
            best = None
            for left in range(1, num_semesters + 1):
                for left_item in schedule[left]:
                    if (
                        left_item.get("course_id") is None
                        or left_item.get("regulatory_required")
                    ):
                        continue
                    left_scoped = bool(left_item.get("_scoped_epvo_semester") and left_item.get("recommended_semester"))
                    left_credits = int(left_item.get("credits") or 0)
                    for right in range(left + 1, num_semesters + 1):
                        for right_item in schedule[right]:
                            if (
                                right_item.get("course_id") is None
                                or right_item.get("regulatory_required")
                            ):
                                continue
                            right_scoped = bool(right_item.get("_scoped_epvo_semester") and right_item.get("recommended_semester"))
                            if not left_scoped and not right_scoped:
                                continue
                            left_rec = int(left_item["recommended_semester"]) if left_scoped else None
                            right_rec = int(right_item["recommended_semester"]) if right_scoped else None
                            right_credits = int(right_item.get("credits") or 0)
                            if (
                                loads[left] - left_credits + right_credits < lower
                                or loads[left] - left_credits + right_credits > upper
                                or loads[right] - right_credits + left_credits < lower
                                or loads[right] - right_credits + left_credits > upper
                            ):
                                continue
                            before = (abs(left - left_rec) if left_rec is not None else 0) + (abs(right - right_rec) if right_rec is not None else 0)
                            after = (abs(right - left_rec) if left_rec is not None else 0) + (abs(left - right_rec) if right_rec is not None else 0)
                            if after >= before:
                                continue
                            trial = dict(mapping)
                            trial[int(left_item["course_id"])] = right
                            trial[int(right_item["course_id"])] = left
                            if not valid_assignment(left_item, right, trial):
                                continue
                            if not valid_assignment(right_item, left, trial):
                                continue
                            gain = before - after
                            if best is None or gain > best[0]:
                                best = (gain, left, left_item, right, right_item)
            if best is None:
                break
            _, left, left_item, right, right_item = best
            left_credits = int(left_item.get("credits") or 0)
            right_credits = int(right_item.get("credits") or 0)
            schedule[left].remove(left_item)
            schedule[right].remove(right_item)
            schedule[left].append(right_item)
            schedule[right].append(left_item)
            loads[left] += right_credits - left_credits
            loads[right] += left_credits - right_credits

    improve_scoped_semester_alignment()
    return schedule
