from __future__ import annotations

from itertools import combinations
from typing import Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.course import Course, course_prerequisites
from app.models.embedding import MatchScore
from app.models.epvo import EpvoDisciplineNormalized
from app.models.project import ProjectVersion
from app.planner.admission import (
    credible_professional_lo_by_course as _credible_professional_lo_by_course,
)
from app.planner.course_policy import (
    education_level_course_allowed as _education_level_course_allowed,
)
from app.planner.domain_evidence import domain_credit_shares, domain_label_matches
from app.planner.scheduler_catalogue import unique_items_by_title as _unique_items_by_title
from app.planner.scheduler_domain_rules import (
    has_foreign_professional_title as _has_foreign_professional_title,
)
from app.planner.scheduler_utils import title_key as _title_key
from app.planner.semester_appropriateness import _repair_semester_appropriateness
from app.planner.semester_domain_metrics import (
    domain_deficit,
    non_domain_hard_count,
    scope_strength,
)
from app.planner.verifier import verify_curriculum_plan
from app.services.epvo_repository import epvo_row_matches_education_level

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
            explicit_matches = [
                domain_label_matches(item.get("domain"), [project_domains[index]])
                for index in range(2)
            ]
            if explicit_matches[1] and not explicit_matches[0]:
                return (0.0, 1.0)
            if explicit_matches[0] and not explicit_matches[1]:
                return (1.0, 0.0)
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
