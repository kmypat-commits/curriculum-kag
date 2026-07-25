"""Compact diagnostic for the real EPVO course pool of one project version."""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict


def values(raw):
    try:
        value = json.loads(raw or "[]")
        return {str(item) for item in value} if isinstance(value, list) else set()
    except (TypeError, json.JSONDecodeError):
        return set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="curriculum_kag.db")
    parser.add_argument("--version", type=int, required=True)
    args = parser.parse_args()
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    project = db.execute(
        "select p.constraints_json from projects p join project_versions v on v.project_id=p.id where v.id=?",
        (args.version,),
    ).fetchone()
    constraints = json.loads(project[0] or "{}")
    groups = {str(constraints.get(key) or "") for key in ("group_code", "secondary_group_code")} - {""}
    directions = {str(constraints.get(key) or "") for key in ("direction_code", "secondary_direction_code")} - {""}
    primary_groups = {str(constraints.get("group_code") or "")} - {""}
    secondary_groups = {str(constraints.get("secondary_group_code") or "")} - {""}
    primary_directions = {str(constraints.get("direction_code") or "")} - {""}
    secondary_directions = {str(constraints.get("secondary_direction_code") or "")} - {""}
    rows = db.execute(
        """
        select c.id, c.course_id, c.title, c.domain, c.credits, max(m.score) model_score,
               m.lo_id
        from match_scores m join courses c on c.id=m.course_id
        where m.project_version_id=?
        group by c.id, m.lo_id
        """,
        (args.version,),
    ).fetchall()
    course_ids = sorted({int(row["id"]) for row in rows})
    epvo_meta = defaultdict(list)
    if course_ids:
        placeholders = ",".join("?" for _ in course_ids)
        for meta in db.execute(
            f"select approved_course_id, group_codes, direction_codes from epvo_disciplines_normalized where approved_course_id in ({placeholders})",
            course_ids,
        ).fetchall():
            epvo_meta[int(meta["approved_course_id"])].append(meta)
    by_course = {}
    lo_counts = defaultdict(int)
    for row in rows:
        item = by_course.setdefault(row["id"], {
            "course_id": row["course_id"], "title": row["title"], "domain": row["domain"], "credits": int(row["credits"] or 0),
            "score": 0.0, "group": False, "direction": False, "primary": False, "secondary": False,
        })
        item["score"] = max(item["score"], float(row["model_score"] or 0.0))
        metas = epvo_meta.get(int(row["id"]), [])
        meta_groups = set().union(*(values(meta["group_codes"]) for meta in metas)) if metas else set()
        meta_directions = set().union(*(values(meta["direction_codes"]) for meta in metas)) if metas else set()
        item["group"] = item["group"] or bool(groups & meta_groups)
        item["direction"] = item["direction"] or bool(directions & meta_directions)
        item["primary"] = item["primary"] or bool(
            primary_groups & meta_groups
            or primary_directions & meta_directions
        )
        item["secondary"] = item["secondary"] or bool(
            secondary_groups & meta_groups
            or secondary_directions & meta_directions
        )
        if float(row["model_score"] or 0.0) >= 0.55:
            lo_counts[int(row["lo_id"])] += 1
    def summary(predicate):
        items = [item for item in by_course.values() if predicate(item)]
        return {"courses": len(items), "credits": sum(item["credits"] for item in items)}
    domain_summary = defaultdict(lambda: {"courses": 0, "credits": 0})
    for item in by_course.values():
        if item["score"] < 0.4:
            continue
        domain_summary[item["domain"]]["courses"] += 1
        domain_summary[item["domain"]]["credits"] += item["credits"]
    print(json.dumps({
        "version": args.version,
        "groups": sorted(groups),
        "directions": sorted(directions),
        "all_scored": summary(lambda item: item["score"] >= 0.4),
        "selected_groups": summary(lambda item: item["score"] >= 0.4 and item["group"]),
        "selected_directions": summary(lambda item: item["score"] >= 0.4 and (item["group"] or item["direction"])),
        "strong_055_directions": summary(lambda item: item["score"] >= 0.55 and (item["group"] or item["direction"])),
        "primary_scope_040": summary(lambda item: item["score"] >= 0.4 and item["primary"]),
        "secondary_scope_040": summary(lambda item: item["score"] >= 0.4 and item["secondary"]),
        "strong_courses_per_lo": dict(sorted(lo_counts.items())),
        "scored_pool_by_domain": dict(domain_summary),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
