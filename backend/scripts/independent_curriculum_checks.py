"""Independent report-level structural checks for TEM curriculum audits.

Uses only Python's standard library and persisted report fields. It does not
import the planner or its verifier. This checks arithmetic and edge ordering,
not educational suitability or whether an inferred edge is pedagogically true.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


TARGET_CREDITS_BY_LEVEL = {"bachelor": 240, "master": 120, "doctorate": 180}


def check_variant(variant: dict, *, target_credits: int, max_load: int,
                  min_load: int = 0, num_semesters: int | None = None) -> list[dict]:
    issues: list[dict] = []
    rows = variant.get("schedule_fingerprint") or []
    if not rows or any(not isinstance(row, list) or len(row) != 3 for row in rows):
        return [{"reason": "missing_or_invalid_schedule_fingerprint"}]
    loads: dict[int, int] = defaultdict(int)
    titles: set[str] = set()
    for semester, title, credits in rows:
        semester, credits = int(semester), int(credits)
        if semester < 1 or credits <= 0:
            issues.append({"reason": "invalid_semester_or_credit", "semester": semester, "credits": credits})
        loads[semester] += credits
        key = " ".join(str(title).casefold().split())
        if key in titles:
            issues.append({"reason": "duplicate_title", "title": title})
        titles.add(key)
    computed_total = sum(loads.values())
    if computed_total != target_credits:
        issues.append({"reason": "target_credits", "actual": computed_total, "required": target_credits})
    if computed_total != int(variant.get("credits") or 0):
        issues.append({"reason": "reported_credit_mismatch", "computed": computed_total, "reported": variant.get("credits")})
    reported_loads = {int(key): int(value) for key, value in (variant.get("semester_loads") or {}).items()}
    if dict(loads) != reported_loads:
        issues.append({"reason": "reported_semester_load_mismatch", "computed": dict(loads), "reported": reported_loads})
    if num_semesters is not None:
        missing = sorted(set(range(1, num_semesters + 1)) - set(loads))
        if missing:
            issues.append({"reason": "missing_semester", "semesters": missing})
        unexpected = sorted(set(loads) - set(range(1, num_semesters + 1)))
        if unexpected:
            issues.append({"reason": "unexpected_semester", "semesters": unexpected})
    for semester, credits in loads.items():
        if credits > max_load:
            issues.append({"reason": "semester_overload", "semester": semester, "actual": credits, "maximum": max_load})
        if credits < min_load:
            issues.append({"reason": "semester_underload", "semester": semester, "actual": credits, "minimum": min_load})
    for edge in variant.get("prerequisite_pairs") or []:
        parent, child = edge.get("prerequisite_semester"), edge.get("course_semester")
        if parent is None or child is None or int(parent) >= int(child):
            issues.append({
                "reason": "prerequisite_not_before_course",
                "prerequisite_id": edge.get("prerequisite_id"),
                "course_id": edge.get("course_id"),
                "prerequisite_semester": parent, "course_semester": child,
            })
    return issues


def check_cohort(report: dict, *, max_load: int, min_load: int = 0) -> dict:
    """Check every persisted case, including incomplete or failed cases."""
    cases = []
    for case in report.get("reports") or []:
        level = case.get("level")
        target = TARGET_CREDITS_BY_LEVEL.get(level)
        variants = case.get("variants") or {}
        checks = {
            code: check_variant(variant, target_credits=target, max_load=max_load, min_load=min_load)
            for code, variant in variants.items()
        } if target is not None else {}
        if target is None:
            checks["_case"] = [{"reason": "unknown_level", "level": level}]
        if not variants:
            checks["_case"] = [{"reason": "no_variants", "status": case.get("status")}]
        cases.append({
            "cohort_index": case.get("cohort_index"),
            "level": level,
            "reported_passed": case.get("passed"),
            "checks": checks,
        })
    bad = [case for case in cases if any(case["checks"].values())]
    return {
        "requested": report.get("requested"),
        "completed": report.get("completed"),
        "independently_checked_cases": len(cases),
        "cases_with_issues": len(bad),
        "issues": bad,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--target-credits", type=int)
    parser.add_argument("--cohort-report", action="store_true")
    parser.add_argument("--max-load", type=int, required=True)
    parser.add_argument("--min-load", type=int, default=0)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if args.cohort_report:
        results = check_cohort(report, max_load=args.max_load, min_load=args.min_load)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 1 if results["cases_with_issues"] else 0
    if args.target_credits is None:
        parser.error("--target-credits is required unless --cohort-report is set")
    results = {
        code: check_variant(variant, target_credits=args.target_credits, max_load=args.max_load, min_load=args.min_load)
        for code, variant in (report.get("variants") or {}).items()
    }
    print(json.dumps({"report": str(args.report), "checks": results}, ensure_ascii=False, indent=2))
    return 0 if results and all(not issues for issues in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
