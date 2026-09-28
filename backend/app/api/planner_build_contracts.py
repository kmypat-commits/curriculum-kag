"""Pure request and publication rules shared by planner build routes."""

from __future__ import annotations

import hashlib
import json


def build_request_hash(project_version_id: int, variants: object) -> str:
    """Return a stable hash of the explicit build command."""
    canonical = json.dumps(
        {"project_version_id": int(project_version_id), "variants": variants},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_requested_variants(variants: object) -> list[str]:
    """Normalize the UI/API selector; the standard build creates A only."""
    if variants in (None, ""):
        requested = ["A"]
    elif variants == "all":
        requested = ["A", "B", "C"]
    elif isinstance(variants, str):
        requested = [item.strip().upper() for item in variants.split(",")]
    else:
        requested = [str(item).strip().upper() for item in variants]
    return list(dict.fromkeys(item for item in requested if item in {"A", "B", "C"}))


def partition_publishable_variants(
    variants: dict[str, dict], rejected_variants: list[dict],
) -> tuple[dict[str, dict], set[str]]:
    """Keep verified variants when a comparison request has partial failure.

    Publication remains strict: an item listed in ``rejected_variants`` is
    never returned as publishable. The caller can safely commit a valid A
    while retaining the diagnostic for a rejected B/C.
    """
    rejected_names = {
        str(row.get("variant") or "").upper()
        for row in rejected_variants
        if isinstance(row, dict) and row.get("variant")
    }
    return (
        {name: value for name, value in variants.items() if name not in rejected_names},
        rejected_names,
    )


def required_exclusion_conflicts(constraints: dict | None) -> list[int]:
    """Return courses that a methodist both requires and excludes."""
    constraints = constraints or {}
    requirements = constraints.get("curriculum_requirements") or {}
    if not isinstance(requirements, dict) or requirements.get("enabled") is not True:
        return []
    excluded = {
        int(value) for value in constraints.get("excluded_course_ids") or []
        if str(value).isdigit()
    }
    required = {
        int(value) for value in requirements.get("required_course_ids") or []
        if str(value).isdigit()
    }
    return sorted(required & excluded)


def generation_readiness(
    constraints: dict | None, *, goal: str | None,
    learning_outcomes_count: int, learning_outcomes: list[str] | None = None,
) -> dict:
    """Return a cheap, deterministic preflight before expensive scoring.

    This validates only the inputs a methodist controls. It intentionally does
    not claim that the catalogue will satisfy LO evidence or final regulatory
    rules; those remain strict planner/verifier responsibilities.
    """
    constraints = constraints or {}
    labels = {
        "education_level": "уровень образования",
        "education_area": "область образования ЕПВО",
        "direction_code": "направление подготовки ЕПВО",
        "group_code": "группа образовательных программ ЕПВО",
        "instruction_language": "язык обучения",
        "duration_years": "срок обучения",
        "total_semesters": "количество семестров",
        "total_credits": "объём кредитов",
        "max_credits_per_semester": "максимальная нагрузка семестра",
    }
    missing = [label for key, label in labels.items() if constraints.get(key) in (None, "", 0)]
    if not str(goal or "").strip():
        missing.append("цель программы")
    if learning_outcomes_count <= 0:
        missing.append("минимум один результат обучения")

    blocking = []
    total_credits = int(constraints.get("total_credits") or 0)
    semesters = int(constraints.get("total_semesters") or 0)
    max_per_semester = int(constraints.get("max_credits_per_semester") or 0)
    tolerance = int(constraints.get("credit_tolerance") or 0)
    if total_credits and semesters and max_per_semester and total_credits > semesters * max_per_semester + tolerance:
        blocking.append("Заданное число кредитов не помещается в установленную семестровую нагрузку.")

    conflicting_courses = required_exclusion_conflicts(constraints)
    if conflicting_courses:
        blocking.append(
            "Дисциплины одновременно обязательны и исключены: "
            + ", ".join(str(course_id) for course_id in conflicting_courses)
            + ". Снимите исключение либо уберите их из обязательных."
        )

    programme_type = str(constraints.get("program_type") or "standard").lower()
    if programme_type in {"interdisciplinary", "joint"}:
        secondary = ("secondary_education_area", "secondary_direction_code", "secondary_group_code")
        if any(constraints.get(key) in (None, "", 0) for key in secondary):
            blocking.append("Для междисциплинарной программы нужно заполнить второе направление ЕПВО.")
        if int(constraints.get("min_domain1_percent") or 0) + int(constraints.get("min_domain2_percent") or 0) > 100:
            blocking.append("Сумма минимальных долей двух областей не может превышать 100%.")

    warnings = []
    clean_goal = " ".join(str(goal or "").split())
    clean_outcomes = [" ".join(str(value or "").split()) for value in (learning_outcomes or [])]
    if 0 < learning_outcomes_count < 4:
        warnings.append("Указано менее четырёх результатов обучения: план можно построить, но методическая проверка будет слабее.")
    if clean_goal and len(clean_goal) < 30:
        warnings.append("Цель сформулирована очень кратко: уточните профессиональный контекст и ожидаемый результат подготовки.")
    short_outcomes = [index + 1 for index, value in enumerate(clean_outcomes) if value and len(value) < 25]
    if short_outcomes:
        warnings.append("Слишком краткие РО: " + ", ".join(f"РО{index}" for index in short_outcomes) + ". Добавьте наблюдаемое действие и предметный контекст.")
    seen_outcomes: dict[str, int] = {}
    duplicate_outcomes = []
    for index, value in enumerate(clean_outcomes, start=1):
        key = value.casefold()
        if not key:
            continue
        if key in seen_outcomes:
            duplicate_outcomes.append((seen_outcomes[key], index))
        else:
            seen_outcomes[key] = index
    if duplicate_outcomes:
        pairs = ", ".join(f"РО{first}/РО{second}" for first, second in duplicate_outcomes)
        warnings.append("Повторяющиеся результаты обучения: " + pairs + ". Объедините или разведите их, иначе подбор дисциплин будет дублироваться.")
    if not constraints.get("group_code"):
        warnings.append("Без группы ОП ЕПВО подбор дисциплин будет слишком широким.")
    return {
        "ready": not missing and not blocking,
        "missing": missing,
        "blocking": blocking,
        "warnings": warnings,
        "checks": {
            "methodist_conflicts": {"required_course_ids": conflicting_courses},
            "goal": bool(str(goal or "").strip()),
            "learning_outcomes": learning_outcomes_count,
            "unique_learning_outcomes": len(seen_outcomes) if clean_outcomes else learning_outcomes_count,
            "catalogue_scope": bool(constraints.get("direction_code") and constraints.get("group_code")),
            "volume": {
                "target_credits": total_credits,
                "capacity_credits": semesters * max_per_semester,
            },
        },
    }


def must_reject_variant(verification: dict | None) -> bool:
    """Return whether a generated variant is unsafe to persist."""
    verification = verification or {}
    quality_reasons = {
        str(item.get("reason"))
        for item in (verification.get("quality_violations") or [])
        if isinstance(item, dict)
    }
    blocking_quality_reasons = {
        "semester_appropriateness",
        "missing_core_competency_blocks",
        "bridge_module_limit_exceeded",
    }
    return bool(
        not verification.get("feasible")
        or int(verification.get("hard_violation_count") or 0) > 0
        or "lo_without_real_course" in quality_reasons
        or quality_reasons.intersection(blocking_quality_reasons)
    )


def activate_only_plan(plan_rows: list, active_plan_id: int | None):
    """Mark exactly one plan active and return it."""
    active_plan = None
    for plan in plan_rows:
        is_active = bool(active_plan_id is not None and plan.id == active_plan_id)
        plan.is_active = 1 if is_active else 0
        if is_active:
            active_plan = plan
    return active_plan
