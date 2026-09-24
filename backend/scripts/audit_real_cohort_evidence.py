"""Independently audit frozen TEM real-cohort manifests and schedule arithmetic."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from independent_curriculum_checks import check_variant


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def audit(first: dict, second: dict, frozen: dict) -> dict:
    input_by_id = {str(row["program_id"]): row for row in frozen["prepared"]}
    findings = []
    seen = set()
    structural_passed = 0
    internally_passed = 0
    failure_reasons = Counter()
    for part, expected_count, report in ((1, 50, first), (2, 30, second)):
        if report.get("completed") != expected_count or len(report.get("reports") or []) != expected_count:
            findings.append({"part": part, "reason": "incomplete_report"})
        for case in report.get("reports") or []:
            program_id = str(case.get("program_id"))
            if program_id in seen or program_id not in input_by_id:
                findings.append({"part": part, "program_id": program_id, "reason": "duplicate_or_unknown_programme"})
                continue
            seen.add(program_id)
            entry = input_by_id[program_id]
            raw = Path(entry["input"]).read_bytes()
            payload = json.loads(raw)
            canonical = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            if sha256(raw) != entry["sha256"] or canonical != entry["canonical_sha256"] or canonical != case.get("input_sha256"):
                findings.append({"part": part, "program_id": program_id, "reason": "input_hash_mismatch"})
            constraints = payload["constraints"]
            nominal = int(constraints["max_credits_per_semester"])
            variant = (case.get("variants") or {}).get("A")
            if variant is None:
                issues = [{"reason": "missing_variant_A"}]
            else:
                issues = check_variant(
                    variant, target_credits=int(constraints["total_credits"]),
                    min_load=max(0, nominal - 3), max_load=nominal + 3,
                )
            if not issues:
                structural_passed += 1
            else:
                failure_reasons.update(row["reason"] for row in issues)
                findings.append({"part": part, "program_id": program_id, "reason": "structural_issue", "issues": issues})
            if case.get("passed"):
                internally_passed += 1
            else:
                if variant is None:
                    failure_reasons["missing_variant_A"] += 1
                else:
                    if variant.get("load_violations"):
                        failure_reasons["internal_load_violation"] += 1
                    if variant.get("lo_without_real_course"):
                        failure_reasons["insufficient_real_course_LO_evidence"] += 1
                    if variant.get("credit_violations"):
                        failure_reasons["internal_credit_violation"] += 1
                    if variant.get("domain_quota_violations"):
                        failure_reasons["internal_domain_quota_violation"] += 1
    if len(seen) != 80 or set(input_by_id) != seen:
        findings.append({"reason": "cohort_identity_mismatch", "seen": len(seen), "frozen": len(input_by_id)})
    return {
        "distinct_programmes": len(seen), "internal_passed": internally_passed,
        "internal_failed": len(seen) - internally_passed,
        "structural_passed": structural_passed,
        "structural_failed": len(seen) - structural_passed,
        "failure_reasons": dict(failure_reasons),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part1", type=Path, required=True)
    parser.add_argument("--part2", type=Path, required=True)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(
        json.loads(args.part1.read_text(encoding="utf-8")),
        json.loads(args.part2.read_text(encoding="utf-8")),
        json.loads(args.input_manifest.read_text(encoding="utf-8")),
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(json.dumps({key: result[key] for key in (
            "distinct_programmes", "internal_passed", "internal_failed",
            "structural_passed", "structural_failed", "failure_reasons",
        )}, ensure_ascii=False))
    else:
        print(rendered, end="")
    return 0 if result["distinct_programmes"] == 80 and result["internal_failed"] == 0 and not result["findings"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
