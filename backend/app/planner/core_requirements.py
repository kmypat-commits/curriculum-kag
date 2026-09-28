"""Shared requirement evaluation. Explicit mappings only, never title guesses."""
from app.schemas.curriculum_requirements import CurriculumRequirements


def effective_requirements(raw):
    parsed = CurriculumRequirements.model_validate(raw or {})
    return parsed.model_dump() if parsed.enabled else None


def evaluate_coverage(raw, schedule, *, confirmed_matches=None):
    """Count only server-verified block/course matches as professional coverage.

    ``accepted_course_ids`` is a candidate list from the request, not proof
    that a methodist reviewed the course content. ``confirmed_matches`` must
    come from the trusted confirmation store, never directly from that request.
    """
    requirements = effective_requirements(raw)
    if requirements is None:
        return {"enabled": False, "passed": True, "core_coverage": [],
                "required_courses": {"requested": [], "included": [], "missing": []},
                "unique_core_credits": 0}
    selected = {int(item["course_id"]): int(item.get("credits") or 0)
                for items in schedule.values() for item in items if item.get("course_id")}
    rows, union = [], set()
    confirmed_matches = confirmed_matches or {}
    for block in requirements["core_blocks"]:
        candidates = set(block["accepted_course_ids"]) & selected.keys()
        ids = sorted(candidates & set(confirmed_matches.get(block["id"], ())))
        unconfirmed = sorted(candidates - set(ids))
        union.update(ids)
        credits = sum(selected[cid] for cid in ids)
        covered = len(ids) >= block["min_courses"] and credits >= block["min_credits"]
        rows.append({"block_id": block["id"], "title": block["title"],
                     "requirement": block["requirement"],
                     "status": "covered" if covered else "unconfirmed" if unconfirmed else "gap",
                     "selected_course_ids": ids, "unconfirmed_course_ids": unconfirmed,
                     "supported_credits": credits})
    requested = requirements["required_course_ids"]
    missing = sorted(set(requested) - selected.keys())
    return {"enabled": True, "core_coverage": rows,
            "required_courses": {"requested": requested,
                                 "included": sorted(set(requested) & selected.keys()), "missing": missing},
            "unique_core_credits": sum(selected[cid] for cid in union),
            "passed": not missing and not any(row["requirement"] == "required" and
                                             row["status"] != "covered" for row in rows)}
