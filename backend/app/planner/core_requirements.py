"""Shared requirement evaluation. Explicit mappings only, never title guesses."""
from app.schemas.curriculum_requirements import CurriculumRequirements


def effective_requirements(raw):
    parsed = CurriculumRequirements.model_validate(raw or {})
    return parsed.model_dump() if parsed.enabled else None


def evaluate_coverage(raw, schedule):
    requirements = effective_requirements(raw)
    if requirements is None:
        return {"enabled": False, "passed": True, "core_coverage": [],
                "required_courses": {"requested": [], "included": [], "missing": []},
                "unique_core_credits": 0}
    selected = {int(item["course_id"]): int(item.get("credits") or 0)
                for items in schedule.values() for item in items if item.get("course_id")}
    rows, union = [], set()
    for block in requirements["core_blocks"]:
        ids = sorted(set(block["accepted_course_ids"]) & selected.keys())
        union.update(ids)
        credits = sum(selected[cid] for cid in ids)
        covered = len(ids) >= block["min_courses"] and credits >= block["min_credits"]
        rows.append({"block_id": block["id"], "title": block["title"],
                     "requirement": block["requirement"],
                     "status": "covered" if covered else "gap",
                     "selected_course_ids": ids, "supported_credits": credits})
    requested = requirements["required_course_ids"]
    missing = sorted(set(requested) - selected.keys())
    return {"enabled": True, "core_coverage": rows,
            "required_courses": {"requested": requested,
                                 "included": sorted(set(requested) & selected.keys()), "missing": missing},
            "unique_core_credits": sum(selected[cid] for cid in union),
            "passed": not missing and not any(row["requirement"] == "required" and
                                             row["status"] != "covered" for row in rows)}
