"""Pure reporting helpers for plan API responses."""
from __future__ import annotations

from app.models.bridge_module import BridgeModule
from app.models.course import Course
from app.models.plan import PlanItem
from app.planner.planner_utils import title_key as _title_key


def academic_classification(course, semester: int, total_semesters: int, role: str, jurisdiction: str = "INTERNATIONAL") -> dict:
    """Return separate RK curriculum cycle and component labels."""
    raw = str(getattr(course, "cycle_component", None) or "").casefold()
    code = str(getattr(course, "course_id", None) or "")
    if "_ood_" in raw or raw.startswith("goso_ood"):
        cycle, source = "ООД", "goso"
    elif "_bd_" in raw or raw.startswith("goso_bd"):
        cycle, source = "БД", "goso"
    elif "_pd_" in raw or raw.startswith("goso_pd"):
        cycle, source = "ПД", "goso"
    elif raw.startswith("goso_research") or raw.startswith("goso_final"):
        cycle, source = "ПД", "goso"
    elif role == "general":
        cycle, source = "ООД", "inferred"
    elif int(semester or 1) <= max(2, int(total_semesters or 8) // 2):
        cycle, source = "БД", "inferred"
    else:
        cycle, source = "ПД", "inferred"
    if "elective" in raw or "по выбору" in raw:
        component = "компонент по выбору"
    elif "university" in raw or "вузов" in raw:
        component = "вузовский компонент"
    elif "practice" in raw:
        component = "практика"
    elif "research" in raw:
        component = "научно-исследовательская работа"
    elif "final" in raw:
        component = "итоговая аттестация"
    else:
        component = "обязательный компонент"
    return {"academic_cycle": cycle, "academic_cycle_source": source, "academic_component": component, "protected_by_goso": str(jurisdiction or "INTERNATIONAL").upper() == "KZ" and code.startswith("GOSO-KZ-")}


def build_change_report(old_snapshot: dict | None, new_snapshot: dict | None) -> dict:
    if not old_snapshot or not new_snapshot:
        return {"available": False, "reason": "Нет старого или нового активного плана для сравнения"}
    old_titles = set(old_snapshot.get("titles") or [])
    new_titles = set(new_snapshot.get("titles") or [])
    added, removed = sorted(new_titles - old_titles), sorted(old_titles - new_titles)
    return {
        "available": True, "old_plan_id": old_snapshot["plan_id"], "new_plan_id": new_snapshot["plan_id"], "variant": new_snapshot["variant"],
        "credits_delta": int(new_snapshot["credits"] or 0) - int(old_snapshot["credits"] or 0),
        "items_delta": int(new_snapshot["items"] or 0) - int(old_snapshot["items"] or 0),
        "bridges_delta": int(new_snapshot["bridges"] or 0) - int(old_snapshot["bridges"] or 0),
        "min_lo_delta": None if old_snapshot.get("min_lo") is None or new_snapshot.get("min_lo") is None else round(float(new_snapshot["min_lo"]) - float(old_snapshot["min_lo"]), 4),
        "quality_before": old_snapshot.get("quality"), "quality_after": new_snapshot.get("quality"), "hard_before": old_snapshot.get("hard"), "hard_after": new_snapshot.get("hard"),
        "added_count": len(added), "removed_count": len(removed), "added_titles_sample": added[:12], "removed_titles_sample": removed[:12],
    }


def plan_snapshot(plan, db) -> dict | None:
    """Create a compact, comparison-safe snapshot of one persisted plan."""
    if not plan:
        return None
    items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
    course_ids = [item.course_id for item in items if item.course_id]
    bridge_ids = [item.bridge_module_id for item in items if item.bridge_module_id]
    courses = {course.id: course for course in db.query(Course).filter(Course.id.in_(course_ids or [-1])).all()}
    bridges = {bridge.id: bridge for bridge in db.query(BridgeModule).filter(BridgeModule.id.in_(bridge_ids or [-1])).all()}
    titles = []
    for item in items:
        if item.course_id and item.course_id in courses:
            titles.append(courses[item.course_id].title)
        elif item.bridge_module_id and item.bridge_module_id in bridges:
            titles.append(bridges[item.bridge_module_id].title)
    verification = (plan.metrics_json or {}).get("verification") or {}
    return {
        "plan_id": plan.id, "variant": plan.variant_type,
        "credits": sum(int(item.credits or 0) for item in items), "items": len(items), "bridges": len(bridge_ids),
        "min_lo": verification.get("min_lo_coverage"), "avg_lo": verification.get("average_lo_coverage"),
        "quality": verification.get("quality_passed"), "hard": verification.get("hard_violation_count"),
        "titles": sorted({_title_key(title) for title in titles if title}),
    }
