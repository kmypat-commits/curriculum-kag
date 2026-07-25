"""Read-only quality audit for saved A/B/C plans through the local API.

The script is deliberately independent of SQLAlchemy and the active database
backend, so the same control can be reused after SQLite -> PostgreSQL migration.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path


def request_json(url: str, token: str | None = None, data: dict | None = None):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def login(base_url: str) -> str:
    email = os.getenv("CURRICULUM_LOCAL_EMAIL", "admin@curriculum-kag.local")
    password = os.getenv("CURRICULUM_LOCAL_PASSWORD", "admin123")
    body = urllib.parse.urlencode({"username": email, "password": password}).encode()
    request = urllib.request.Request(
        f"{base_url}/auth/login",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))["access_token"]


def title_key(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def audit_variant(base_url: str, token: str, version_id: int, variant: dict, constraints: dict) -> dict:
    code = variant.get("variant_type") or "?"
    schedule = variant.get("schedule") or {}
    units = [unit for semester in schedule.values() for unit in (semester or [])]
    titles = [title_key(unit.get("title")) for unit in units if title_key(unit.get("title"))]
    duplicates = sorted({title for title in titles if titles.count(title) > 1})
    verification = variant.get("verification") or variant.get("metrics", {}).get("verification") or {}
    audit = verification.get("pedagogical_audit") or {}
    suspicious = variant.get("suspicious_courses") or []
    sources = request_json(
        f"{base_url}/planner/{version_id}/lo-coverage-sources?variant={code}", token
    )
    pairs = [
        (row.get("lo_code"), source.get("course_id"))
        for row in sources.get("items", [])
        for source in row.get("real_sources", [])
    ]
    loads = {
        str(semester): sum(int(unit.get("credits") or 0) for unit in semester_units)
        for semester, semester_units in schedule.items()
    }
    total = sum(loads.values())
    target = int(constraints.get("total_credits") or 0)
    tolerance = int(constraints.get("credit_tolerance") or 0)
    course_lo_violations = int(verification.get("course_lo_violations") or 0)
    wrong_level = [row for row in suspicious if "wrong_education_level" in (row.get("reasons") or [])]
    checks = {
        "credits_within_tolerance": target <= total <= target + tolerance,
        "no_duplicate_titles": not duplicates,
        "no_hard_violations": int(verification.get("hard_violation_count") or 0) == 0,
        "every_course_has_lo": course_lo_violations == 0 and not audit.get("weak_courses") and not audit.get("structural_foundations"),
        "no_wrong_education_level": not wrong_level,
        "no_semester_misplacements": not audit.get("semester_misplacements"),
        "no_duplicate_lo_course_sources": len(pairs) == len(set(pairs)),
        "all_los_have_real_course": int(sources.get("summary", {}).get("real_confirmed") or 0) == int(sources.get("summary", {}).get("los") or 0),
    }
    return {
        "plan_id": variant.get("plan_id"),
        "variant": code,
        "active": bool(variant.get("is_active")),
        "credits": total,
        "semester_loads": loads,
        "courses": sum(1 for unit in units if unit.get("course_id")),
        "bridges": sum(1 for unit in units if unit.get("bridge_module_id")),
        "hard_violations": int(verification.get("hard_violation_count") or 0),
        "course_lo_violations": course_lo_violations,
        "wrong_level_courses": [{"title": row.get("title"), "semester": row.get("semester")} for row in wrong_level],
        "duplicate_titles": duplicates,
        "lo_summary": sources.get("summary") or {},
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projects", nargs="+", type=int, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    token = login(args.base_url)
    projects = []
    for project_id in args.projects:
        project = request_json(f"{args.base_url}/projects/{project_id}", token)
        version_id = int(project["latest_version"]["id"])
        variants = request_json(f"{args.base_url}/planner/{version_id}/variants", token)
        constraints = project.get("constraints") or {}
        project_result = {
            "project_id": project_id,
            "version_id": version_id,
            "title": project.get("title"),
            "education_level": constraints.get("education_level"),
            "group_codes": [value for value in (constraints.get("group_code"), constraints.get("secondary_group_code")) if value],
            "variants": [audit_variant(args.base_url, token, version_id, row, constraints) for row in variants],
        }
        project_result["passed"] = bool(project_result["variants"]) and all(row["passed"] for row in project_result["variants"])
        projects.append(project_result)
    level_counts = {}
    for project in projects:
        level = str(project.get("education_level") or "unknown")
        level_counts[level] = level_counts.get(level, 0) + 1
    report = {
        "schema_version": 1,
        "generated_at_epoch": int(time.time()),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "project_count": len(projects),
        "education_level_counts": level_counts,
        "missing_control_levels": [level for level in ("bachelor", "master", "doctorate") if not level_counts.get(level)],
        "passed": bool(projects) and all(project["passed"] for project in projects),
        "projects": projects,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "passed": report["passed"],
        "projects": report["project_count"],
        "levels": level_counts,
        "missing_levels": report["missing_control_levels"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
