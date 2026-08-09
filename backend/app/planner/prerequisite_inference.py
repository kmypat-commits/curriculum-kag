from __future__ import annotations

from typing import Dict, List

from app.planner.scheduler_prerequisites import prerequisite_concepts
from app.planner.scheduler_utils import title_key


def infer_schedule_prerequisites(
    schedule: Dict[int, List[Dict]],
) -> Dict[str, float | int]:
    """Add conservative prerequisite edges inside one final plan.

    Inference is plan-local: it only links selected courses to courses in an
    earlier semester and never mutates the shared repository.
    """
    semester_by_course = {
        int(item["course_id"]): int(semester)
        for semester, items in schedule.items()
        for item in items
        if item.get("course_id") is not None
    }
    items_by_course = {
        int(item["course_id"]): item
        for items in schedule.values()
        for item in items
        if item.get("course_id") is not None
    }
    concepts_by_course = {
        course_id: prerequisite_concepts(item.get("title"))
        for course_id, item in items_by_course.items()
    }
    regulatory_course_ids = {
        course_id
        for course_id, item in items_by_course.items()
        if item.get("regulatory_required")
    }
    dependency_map = {
        "artificial_intelligence": {"algorithms": 6, "data_analysis": 5, "programming": 4},
        "security": {"networks": 6, "operating_systems": 5, "programming": 3},
        "information_systems": {"database": 5, "programming": 3, "data_analysis": 3},
        "data_analysis": {"database": 4, "algorithms": 4, "research": 3},
        "validation": {"programming": 4, "research": 5},
        "project_application": {"project_management": 5, "research": 5, "programming": 3},
        "distributed_systems": {"networks": 5, "operating_systems": 5, "programming": 3},
        "robotics": {"algorithms": 5, "programming": 4, "artificial_intelligence": 3},
        "web": {"programming": 4, "database": 3, "networks": 2},
    }
    inferred = 0
    existing = 0
    covered_targets: set[int] = set()
    for course_id, item in items_by_course.items():
        semester = semester_by_course[course_id]
        safe_existing = sorted({
            int(prerequisite_id)
            for prerequisite_id in (item.get("prerequisites") or [])
            if int(prerequisite_id) in semester_by_course
            and semester_by_course[int(prerequisite_id)] < semester
        })
        if safe_existing:
            item["prerequisites"] = safe_existing
            existing += len(safe_existing)
            covered_targets.add(course_id)
            continue
        target_concepts = concepts_by_course.get(course_id, set())
        if not target_concepts:
            item["prerequisites"] = []
            continue
        ranked = []
        for candidate_id, candidate_semester in semester_by_course.items():
            if candidate_semester >= semester or candidate_id == course_id:
                continue
            if candidate_id in regulatory_course_ids:
                continue
            candidate_concepts = concepts_by_course.get(candidate_id, set())
            if not candidate_concepts:
                continue
            score = 6 * len(target_concepts & candidate_concepts)
            for target_concept in target_concepts:
                for prerequisite_concept, weight in dependency_map.get(target_concept, {}).items():
                    if prerequisite_concept in candidate_concepts:
                        score += weight
            target_key = title_key(item.get("title"))
            if "research" in candidate_concepts and any(
                marker in target_key
                for marker in ("метод", "анализ", "модел", "эксперимент", "исслед")
            ):
                score += 3
            if score >= 4:
                ranked.append((
                    score,
                    candidate_semester,
                    int(items_by_course[candidate_id].get("credits") or 0),
                    candidate_id,
                ))
        ranked.sort(reverse=True)
        selected = []
        used_concepts: set[str] = set()
        for _, _, _, candidate_id in ranked:
            candidate_concepts = concepts_by_course[candidate_id]
            if selected and candidate_concepts <= used_concepts:
                continue
            selected.append(candidate_id)
            used_concepts.update(candidate_concepts)
            if len(selected) == 2:
                break
        item["prerequisites"] = sorted(selected)
        if selected:
            item["prerequisite_inference"] = {
                "method": "plan_local_semantic_ontology",
                "course_ids": sorted(selected),
            }
            inferred += len(selected)
            covered_targets.add(course_id)
    total_edges = existing + inferred
    real_courses = len(items_by_course)
    return {
        "edge_count": total_edges,
        "existing_edge_count": existing,
        "inferred_edge_count": inferred,
        "covered_course_count": len(covered_targets),
        "real_course_count": real_courses,
        "edge_density": round(total_edges / max(real_courses, 1), 4),
    }
