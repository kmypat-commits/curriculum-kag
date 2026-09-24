"""Start two non-overlapping real-programme cohorts after regression completes.

This coordinator runs one heavyweight audit at a time. Every child and its
attempt ledger are persisted by audit_quality_cohort.py. It never changes the
frozen inputs or replaces a failed programme after seeing its result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from audit_quality_cohort import atomic_write_json, process_is_alive


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_digest(root: Path) -> str:
    """Pin executable planner/evaluation code across both real batches."""
    files = sorted((root / "backend" / "app").rglob("*.py"))
    files += [
        root / "backend" / "scripts" / "audit_cross_level_generation.py",
        root / "backend" / "scripts" / "audit_quality_cohort.py",
        Path(__file__).resolve(),
    ]
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engineering-report", type=Path, required=True)
    parser.add_argument("--real-input-manifest", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    coordinator = args.output_prefix.with_name(args.output_prefix.name + "-coordinator.json")
    first = args.output_prefix.with_name(args.output_prefix.name + "-part1.json")
    second = args.output_prefix.with_name(args.output_prefix.name + "-part2.json")
    if coordinator.exists() or first.exists() or second.exists():
        parser.error("one or more output reports already exist; refusing to overwrite")
    frozen_code_sha = source_digest(root)
    frozen_input_sha = hashlib.sha256(args.real_input_manifest.read_bytes()).hexdigest()
    base = {
        "runner_pid": os.getpid(), "source_sha256": frozen_code_sha,
        "input_manifest_sha256": frozen_input_sha,
        "engineering_report": str(args.engineering_report),
        "input_manifest": str(args.real_input_manifest),
        "first_report": str(first), "second_report": str(second),
    }
    atomic_write_json(coordinator, {**base, "status": "waiting_for_engineering", "started_at": time.time()})
    while True:
        engineering = read_json(args.engineering_report)
        status = engineering.get("status")
        if status in {"passed", "failed"} and not process_is_alive(
            engineering.get("runner_pid"), engineering.get("runner_identity")
        ):
            break
        if status not in {"running", "passed", "failed"} or (
            status == "running" and not process_is_alive(
                engineering.get("runner_pid"), engineering.get("runner_identity")
            )
        ):
            atomic_write_json(coordinator, {**base, "status": "blocked", "reason": "engineering runner missing or unexpected status"})
            return 2
        time.sleep(20)
    atomic_write_json(coordinator, {**base, "status": "engineering_finished", "engineering_status": status})
    for part, count, offset, output in ((1, 50, 0, first), (2, 30, 50, second)):
        if source_digest(root) != frozen_code_sha or hashlib.sha256(args.real_input_manifest.read_bytes()).hexdigest() != frozen_input_sha:
            atomic_write_json(coordinator, {**base, "status": "blocked", "reason": "code or input manifest changed before real batch", "part": part})
            return 2
        atomic_write_json(coordinator, {**base, "status": "running", "part": part, "engineering_status": status})
        command = [
            sys.executable, str(root / "backend" / "scripts" / "audit_quality_cohort.py"),
            "--count", str(count), "--case-offset", str(offset),
            "--cohort", "breadth", "--variants", "A", "--timeout", "900",
            "--real-input-manifest", str(args.real_input_manifest),
            "--output", str(output),
        ]
        with output.with_suffix(".stdout.log").open("wb") as stdout, output.with_suffix(".stderr.log").open("wb") as stderr:
            exit_code = subprocess.call(command, cwd=root / "backend", stdout=stdout, stderr=stderr)
        if not output.exists():
            atomic_write_json(coordinator, {**base, "status": "blocked", "reason": "missing child report", "part": part, "exit_code": exit_code})
            return 2
        child = read_json(output)
        if child.get("completed") != count or child.get("status") not in {"passed", "failed"}:
            atomic_write_json(coordinator, {**base, "status": "blocked", "reason": "incomplete child report", "part": part, "exit_code": exit_code})
            return 2
    reports = [read_json(first), read_json(second)]
    first_ids = {row.get("program_id") for row in reports[0]["reports"]}
    second_ids = {row.get("program_id") for row in reports[1]["reports"]}
    if first_ids & second_ids or len(first_ids | second_ids) != 80:
        atomic_write_json(coordinator, {**base, "status": "blocked", "reason": "programme identities are not disjoint"})
        return 2
    passed = sum(int(row["passed"]) for row in reports)
    failed = sum(int(row["failed"]) for row in reports)
    atomic_write_json(coordinator, {
        **base, "status": "passed" if failed == 0 else "failed",
        "completed": 80, "passed": passed, "failed": failed,
        "distinct_programme_count": len(first_ids | second_ids),
        "engineering_status": status, "finished_at": time.time(),
    })
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
