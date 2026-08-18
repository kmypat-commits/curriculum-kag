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
from app.planner.domain_evidence import domain_credit_shares
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
from app.planner.scoped_epvo_semesters import apply_scoped_epvo_semesters as _apply_scoped_epvo_semesters
from app.planner.semester_appropriateness import _repair_semester_appropriateness


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
    # Late selection/credit repairs may have consumed the small initial pool.
    # Quota repair needs the complete programme-scored repository, otherwise a
    # real secondary-domain discipline can be invisible despite its EPVO
    # direction and a credible LO link.
    candidate_ids |= {
        int(course_id)
        for (course_id,) in db.query(MatchScore.course_id).filter(
            MatchScore.project_version_id == project_version.id,
        ).distinct().all()
    }
    scope_pairs = [
        (
            str(constraints.get("group_code") or ""),
            str(constraints.get("direction_code") or ""),
        ),
        (
            str(constraints.get("secondary_group_code") or ""),
            str(constraints.get("secondary_direction_code") or ""),
        ),
    ]

    def scope_strength(values: set[str], group: str, direction: str) -> int:
        if group and group in values:
            return 3
        if direction and direction in values:
            return 2
        return 0

    scope_weights: Dict[int, list[int]] = {}
    for row in db.query(EpvoDisciplineNormalized).filter(
        EpvoDisciplineNormalized.approved_course_id.in_(candidate_ids or {-1})
    ).all():
        if not row.approved_course_id or not epvo_row_matches_education_level(
            row, constraints.get("education_level")
        ):
            continue
        groups = {str(value or "") for value in (row.group_codes or [])}
        directions = {str(value or "") for value in (row.direction_codes or [])}
        weights = scope_weights.setdefault(int(row.approved_course_id), [0, 0])
        for index, (group, direction) in enumerate(scope_pairs):
            weights[index] = max(
                weights[index],
                scope_strength(groups, group, direction),
            )

    def domain_shares(item: Dict) -> tuple[float, float]:
        course_id = item.get("course_id")
        if course_id is not None and int(course_id) in scope_weights:
            primary, secondary = scope_weights[int(course_id)]
            return domain_credit_shares(primary, secondary)
        item_domain = str(item.get("domain") or "").casefold().strip()
        matches = [
            index for index, domain in enumerate(project_domains)
            if domain and (domain in item_domain or item_domain in domain)
        ]
        if len(matches) == 1:
            return (1.0, 0.0) if matches[0] == 0 else (0.0, 1.0)
        if len(matches) == 2:
            return (0.5, 0.5)
        return (0.0, 0.0)

    credible_candidates = _credible_professional_lo_by_course(
        project_version, candidate_ids, db
    )
    candidate_courses = {
        course.id: course
        for course in db.query(Course).filter(Course.id.in_(candidate_ids or {-1})).all()
    }
    max_score_by_course = {
        int(course_id): float(max_score or 0.0)
        for course_id, max_score in db.query(
            MatchScore.course_id,
            func.max(MatchScore.score),
        ).filter(
            MatchScore.project_version_id == project_version.id,
            MatchScore.course_id.in_(candidate_ids or {-1}),
        ).group_by(MatchScore.course_id).all()
    }
    prerequisite_map: Dict[int, List[int]] = {}
    for row in db.execute(
        course_prerequisites.select().where(
            course_prerequisites.c.course_id.in_(candidate_ids or {-1})
        )
    ).fetchall():
        prerequisite_map.setdefault(int(row.course_id), []).append(
            int(row.prerequisite_id)
        )
    expanded_pool = [dict(item) for item in candidate_pool]
    existing_pool_ids = {
        int(item["course_id"])
        for item in expanded_pool if item.get("course_id") is not None
    }
    for course_id, course in candidate_courses.items():
        if (
            course_id in existing_pool_ids
            or course_id not in scope_weights
            or str(course.course_id or "").startswith("GOSO-KZ-")
            or not _education_level_course_allowed(
                course, constraints.get("education_level")
            )
            or _has_foreign_professional_title(course, project_domains)
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
            "admission_score": round(max_score_by_course.get(course.id, 0.0), 4),
            "selection_method": "final_domain_scope_candidate",
        })
    candidates = [
        dict(item) for item in _unique_items_by_title(expanded_pool)
        if (
            item.get("course_id") is not None
            and max(domain_shares(item)) > 0.0
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
            candidate_shares = domain_shares(candidate)
            if (
                not any(candidate_shares[index] > 0.0 for index in missing_domains)
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
                and any(domain_shares(item)[index] <= 0.0 for index in missing_domains)
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
                if any(
                    domain_shares(candidate)[index] > 0.0
                    for index in missing_domains
                )
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
                and any(
                    domain_shares(item)[index] <= 0.0
                    for index in missing_domains
                )
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
                        trial[target].append(replacement)
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

    def balance_semester_with_bridge(
        trial: Dict[int, List[Dict]],
        semester_number: int,
        course_credit_delta: int,
    ) -> bool:
        """Keep a semester's load intact without ever changing a real course.

        A real EPVO course is atomic.  During a late-course swap its 3/4/5
        credit value can nevertheless differ from the displaced course.  An
        explicit generated bridge is the only flexible item in a plan, so it
        may absorb at most the small delta while staying in the 3--7 range.
        This makes a pedagogically valid exchange possible without hiding a
        credit change in a repository course.
        """
        if not course_credit_delta:
            return True
        bridge_options = [
            (index, item)
            for index, item in enumerate(trial.get(semester_number, []))
            if item.get("bridge_module_id") is not None
            and 3 <= int(item.get("credits") or 0) - course_credit_delta <= 7
        ]
        if not bridge_options:
            return False
        bridge_index, bridge_item = min(
            bridge_options,
            key=lambda row: int(row[1].get("credits") or 0),
        )
        adjusted_bridge = dict(bridge_item)
        adjusted_bridge["credits"] = (
            int(bridge_item.get("credits") or 0) - course_credit_delta
        )
        adjusted_bridge["selection_method"] = (
            f"{bridge_item.get('selection_method') or 'bridge'}"
            "+admission_credit_exchange"
        )
        trial[semester_number][bridge_index] = adjusted_bridge
        return True

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
