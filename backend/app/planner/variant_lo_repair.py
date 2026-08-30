"""Repair professional learning-outcome gaps in an assembled variant."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import partial
from typing import Any

from app.models.bridge_module import BridgeModule
from app.models.embedding import MatchScore
from app.planner.course_policy import course_role_rank
from app.planner.variant_coverage import coverage_objective, coverage_state


def close_professional_lo_gaps(
    items: list[dict],
    *,
    professional_scope: bool,
    version: Any,
    db: Any,
    project_version_id: int,
    courses: Mapping[int, Any],
    constraints: Mapping[str, Any],
    project_domains: Sequence[str],
    aggregates: Mapping[int, Mapping[str, Any]],
    prereq_ids_by_course: Mapping[int, Sequence[int]],
    scope_rank: Callable[[Any], int],
    priority_rank: Callable[[Any], int],
    is_project_domain: Callable[[Any], bool],
    variant_type: str,
    coverage_threshold: float,
    unique_items_by_title: Callable[[list[dict]], list[dict]],
    bridge_item: Callable[[Any], dict],
) -> list[dict]:
    """Replace weak same-credit items with evidence-bearing EPVO courses.

    Synthetic bridges are created only after the real in-scope catalogue has
    been exhausted. Regulatory and prerequisite-protected items are never
    silently replaced.
    """
    if not professional_scope:
        return items
    normalized = [dict(item) for item in items]
    lo_by_id = {
        lo.id: lo
        for lo in version.learning_outcomes
        if not str(lo.lo_code or "").startswith("LO-GOSO-")
    }
    if not lo_by_id:
        return normalized

    selected_course_ids = [
        int(item["course_id"]) for item in normalized if item.get("course_id")
    ]
    score_by_course: dict[int, dict[str, float]] = {}
    for match in db.query(MatchScore).filter(
        MatchScore.project_version_id == project_version_id,
        MatchScore.lo_id.in_(list(lo_by_id)),
    ).all():
        lo = lo_by_id.get(match.lo_id)
        if not lo:
            continue
        expert = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
        effective = max(float(match.score or 0.0), expert)
        score_by_course.setdefault(int(match.course_id), {})[lo.lo_code] = max(
            score_by_course.setdefault(int(match.course_id), {}).get(lo.lo_code, 0.0),
            effective,
        )

    state = partial(
        coverage_state,
        lo_codes=[lo.lo_code for lo in lo_by_id.values()],
        score_by_course=score_by_course,
        required_coverage=coverage_threshold,
    )
    objective = partial(coverage_objective, state=state)
    coverage, _maximums, missing = state(normalized)
    if not missing:
        return normalized

    selected_ids = {
        item.get("course_id")
        for item in normalized
        if item.get("course_id") is not None
    }
    protected_ids = {
        prerequisite
        for item in normalized
        for prerequisite in (item.get("prerequisites") or [])
        if prerequisite in selected_ids
    }
    missing_lo_ids = {lo.id for lo in lo_by_id.values() if lo.lo_code in missing}
    candidate_evidence: dict[int, dict[str, Any]] = {}
    if missing_lo_ids:
        for match in db.query(MatchScore).filter(
            MatchScore.project_version_id == project_version_id,
            MatchScore.lo_id.in_(missing_lo_ids),
            MatchScore.score >= 0.3,
        ).all():
            course = courses.get(int(match.course_id))
            if (
                not course
                or course.id in selected_ids
                or not str(course.course_id or "").startswith("EPVO-")
                or not is_project_domain(course)
            ):
                continue
            # A strong programme-specific match is sufficient evidence for a
            # real LO repair even when the imported EPVO scope stamp is absent
            # on that catalogue row.  Domain admission remains mandatory, so
            # this cannot admit a foreign professional discipline.
            if scope_rank(course) <= 0 and float(match.score or 0.0) < 0.55:
                continue
            lo = lo_by_id.get(match.lo_id)
            if not lo:
                continue
            evidence = candidate_evidence.setdefault(
                course.id,
                {"los": set(), "max": 0.0, "expert": 0.0, "scores": {}},
            )
            expert_value = float((match.evidence_json or {}).get("epvo_expert_score") or 0.0)
            effective_score = max(float(match.score or 0.0), expert_value)
            if effective_score < 0.4:
                continue
            evidence["los"].add(lo.lo_code)
            evidence["max"] = max(evidence["max"], effective_score)
            evidence["scores"][lo.lo_code] = max(
                evidence["scores"].get(lo.lo_code, 0.0), effective_score
            )
            evidence["expert"] = max(evidence["expert"], expert_value)

    real_candidates = sorted(
        (courses[cid] for cid in candidate_evidence),
        key=lambda course: (
            len(candidate_evidence[course.id]["los"]),
            candidate_evidence[course.id]["expert"] > 0,
            candidate_evidence[course.id]["expert"],
            candidate_evidence[course.id]["max"],
            scope_rank(course),
            priority_rank(course),
        ),
        reverse=True,
    )
    for candidate in real_candidates:
        evidence = candidate_evidence[candidate.id]
        still_missing = set(missing) & set(evidence["los"])
        if not still_missing:
            continue
        candidate_credits = int(candidate.credits or 5)
        candidate_item = {
            "course_id": candidate.id,
            "title": candidate.title,
            "domain": candidate.domain,
            "credits": candidate_credits,
            "recommended_semester": candidate.recommended_semester,
            "prerequisites": prereq_ids_by_course.get(candidate.id, []),
            "type": candidate.cycle_component or "mandatory",
            "selection_method": "epvo_lo_gap_repair",
            "selection_evidence": {
                "target_los": sorted(still_missing),
                "model_score": round(float(evidence["max"]), 4),
                "epvo_expert_score": round(float(evidence["expert"]), 4),
            },
        }
        current_objective = objective(normalized)
        best_trial = None
        best_objective = current_objective
        for index, item in enumerate(normalized):
            if (
                item.get("bridge_module_id") is not None
                and int(item.get("credits") or 0) == candidate_credits
            ):
                pass
            else:
                old_course = courses.get(item.get("course_id"))
                if (
                    not old_course
                    or old_course.id in protected_ids
                    or item.get("regulatory_required")
                    or int(item.get("credits") or 0) != candidate_credits
                ):
                    continue
            trial = [dict(value) for value in normalized]
            trial[index] = dict(candidate_item)
            trial_objective = objective(trial)
            if trial_objective > best_objective:
                best_objective = trial_objective
                best_trial = trial
        if best_trial is None:
            continue
        normalized = best_trial
        selected_ids.add(candidate.id)
        coverage, _maximums, missing = state(normalized)
        if not missing:
            return unique_items_by_title(normalized)

    if not constraints.get("allow_new_courses", True):
        return unique_items_by_title(normalized)
    current_bridge_count = sum(
        1 for item in normalized if item.get("bridge_module_id") is not None
    )
    slots = max(0, int(constraints.get("max_new_courses", 5)) - current_bridge_count)
    if slots <= 0:
        return normalized
    selected_ids = {
        item.get("course_id")
        for item in normalized
        if item.get("course_id") is not None
    }
    protected_ids = {
        prerequisite
        for item in normalized
        for prerequisite in (item.get("prerequisites") or [])
        if prerequisite in selected_ids
    }
    replaceable = []
    for index, item in enumerate(normalized):
        course = courses.get(item.get("course_id"))
        if not course or course.id in protected_ids:
            continue
        evidence = aggregates.get(course.id, {})
        replaceable.append(
            (
                course_role_rank(course, project_domains),
                priority_rank(course),
                float(evidence.get("max") or 0.0),
                int(course.credits or item.get("credits") or 5),
                index,
                item,
            )
        )
    replaceable.sort(key=lambda row: (row[0], row[1], row[2], -row[3]))
    module_count = min(slots, len(missing), len(replaceable))
    if module_count <= 0:
        return normalized
    total_semesters = int(constraints.get("total_semesters", 8) or 8)
    chunks = [missing[index::module_count] or missing for index in range(module_count)]
    support_by_course: dict[int, list[str]] = {}
    if selected_course_ids:
        for match in db.query(MatchScore).filter(
            MatchScore.project_version_id == project_version_id,
            MatchScore.course_id.in_(selected_course_ids),
            MatchScore.score >= 0.4,
        ).all():
            lo = lo_by_id.get(match.lo_id)
            if lo:
                support_by_course.setdefault(int(match.course_id), []).append(lo.lo_code)
    replacement_indexes = []
    modules = []
    for index in range(module_count):
        _role, _priority, _score, credits, item_index, old_item = replaceable[index]
        credits = max(3, int(credits or 3))
        codes = list(
            dict.fromkeys(
                [
                    *chunks[index],
                    *support_by_course.get(int(old_item.get("course_id") or 0), []),
                ]
            )
        )
        code = f"LO_GAP_BRIDGE_{project_version_id}_{variant_type}_{index + 1}"
        title = f"Модуль закрытия пробелов результатов обучения {', '.join(codes)}"
        module = db.query(BridgeModule).filter(
            BridgeModule.project_version_id == project_version_id,
            BridgeModule.course_id == code,
        ).first()
        payload = {
            "title": title,
            "goal": f"Закрыть недостаточно подтверждённые результаты обучения: {', '.join(codes)}.",
            "description": (
                "Автоматически созданный bridge-модуль заменяет слабую дисциплину, "
                "когда текущий учебный план не подтверждает один или несколько результатов обучения."
            ),
            "credits": credits,
            "recommended_semester": max(2, min(total_semesters - 1, 3 + index)),
            "learning_outcomes": [
                f"Демонстрировать достижение результатов обучения {', '.join(codes)} на практическом кейсе.",
                "Связывать теоретические знания, инструменты и доказательства с требованиями образовательной программы.",
            ],
            "topics": [
                "Диагностика пробела результата обучения",
                "Практический кейс и доказательства достижения",
                "Инструменты, методы и ограничения",
                "Портфолио результата обучения",
            ],
            "assessment_methods": ["практический кейс", "портфолио", "защита проекта"],
            "target_los": codes,
        }
        if module is None:
            module = BridgeModule(
                project_version_id=project_version_id,
                course_id=code,
                prerequisites=[],
                source_chunks_json=[],
                generation_params_json={"mode": "professional_lo_gap_bridge", "variant": variant_type},
                **payload,
            )
            db.add(module)
        else:
            for key, value in payload.items():
                setattr(module, key, value)
            module.prerequisites = []
            module.generation_params_json = {
                "mode": "professional_lo_gap_bridge",
                "variant": variant_type,
            }
        modules.append(module)
        replacement_indexes.append(item_index)
    db.flush()
    for item_index, module in zip(replacement_indexes, modules):
        normalized[item_index] = bridge_item(module)
        normalized[item_index]["selection_method"] = "professional_lo_gap_bridge"
    return unique_items_by_title(normalized)
