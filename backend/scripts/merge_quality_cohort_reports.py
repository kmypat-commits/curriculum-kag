"""Produce one auditable summary from non-overlapping quality-cohort runs.

The merge is deliberately conservative: it accepts only terminal reports whose
case identities do not overlap.  A combined total is therefore not a claim
that two partial runs happened to add up to the requested number of cases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def load_terminal_report(path: Path) -> dict:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(report, dict) or report.get("status") not in {"passed", "failed"}:
        raise ValueError(f"{path} is not a terminal cohort report")
    if report.get("completed") != report.get("requested"):
        raise ValueError(f"{path} has incomplete execution")
    reports = report.get("reports")
    if not isinstance(reports, list) or len(reports) != report["requested"]:
        raise ValueError(f"{path} has an invalid case list")
    return report


def case_identity(report: dict, row: dict) -> tuple[int, str]:
    index = row.get("case_index")
    if not isinstance(index, int):
        raise ValueError("case report lacks integer case_index")
    explicit_hash = str(row.get("input_sha256") or row.get("input_hash") or "")
    if explicit_hash:
        return index, explicit_hash
    # Synthetic breadth controls are constructed from the parent manifest,
    # rather than a separate JSON brief. Bind their identity to that exact
    # manifest row so null ``input_sha256`` is never mistaken for evidence.
    manifest_cases = ((report.get("manifest") or {}).get("cases") or [])
    matches = [case for case in manifest_cases if case.get("case_index") == index]
    if len(matches) != 1:
        raise ValueError("case report lacks a frozen input identity")
    canonical = json.dumps(matches[0], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return index, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def combine(reports: list[dict]) -> dict:
    cases = [row for report in reports for row in report["reports"]]
    identities = [case_identity(report, row) for report in reports for row in report["reports"]]
    indexes = [identity[0] for identity in identities]
    if len(indexes) != len(set(indexes)):
        raise ValueError("cohort reports overlap in case_index")
    if len(identities) != len(set(identities)):
        raise ValueError("cohort reports overlap in frozen input identity")
    passed = [row for row in cases if row.get("passed") is True]
    failed = [row for row in cases if row.get("passed") is not True]
    source_hashes = [
        hashlib.sha256(json.dumps(report, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        for report in reports
    ]
    return {
        "schema_version": 1,
        "status": "passed" if not failed else "failed",
        "scope": (
            "Disposable functional generation audit. It measures declared planner "
            "constraints only and is not independent expert, accreditation, or educational-effectiveness validation."
        ),
        "requested": len(cases),
        "completed": len(cases),
        "passed": len(passed),
        "failed": len(failed),
        "case_indexes": sorted(indexes),
        "source_report_sha256": source_hashes,
        "by_level_profile": {
            f"{level}/{profile}": {
                "count": sum(1 for row in cases if row.get("level") == level and row.get("profile") == profile),
                "passed": sum(1 for row in passed if row.get("level") == level and row.get("profile") == profile),
            }
            for level, profile in {(str(row.get("level")), str(row.get("profile"))) for row in cases}
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        merged = combine([load_terminal_report(path) for path in args.input])
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: merged[key] for key in ("status", "requested", "passed", "failed")}, ensure_ascii=False))
    return 0 if merged["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
