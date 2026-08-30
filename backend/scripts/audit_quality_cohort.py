"""Run a programme-level quality cohort using disposable control projects.

Each child audit creates one temporary programme, validates its A/B/C (or
standard) plan, and removes the project in a finally block.  No user project
or production plan is modified.  The cohort report separates level/profile
and records real-course, bridge, GOSO and hard-violation outcomes.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--output", default=".runtime/quality-cohort.json")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Продолжить незавершённый прогон из существующего progress-файла.",
    )
    parser.add_argument(
        "--variants", nargs="+", choices=("A", "B", "C"), default=["A", "B", "C"],
        help="Варианты для дочернего acceptance-аудита (по умолчанию A B C).",
    )
    args = parser.parse_args()
    if not 1 <= args.count <= 50:
        parser.error("count must be between 1 and 50")
    profiles = [
        ("bachelor", "standard"),
        ("master", "standard"),
        ("doctorate", "standard"),
        ("bachelor", "ict-medicine"),
        ("bachelor", "ict-agro"),
    ]
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    reports: list[dict] = []
    if args.resume and output.exists():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
            if previous.get("status") == "running" and previous.get("requested") == args.count:
                reports = [row for row in previous.get("reports", []) if isinstance(row, dict)]
        except (OSError, json.JSONDecodeError):
            reports = []
    if reports:
        print(json.dumps({"status": "resuming", "completed": len(reports), "requested": args.count}, ensure_ascii=False))
    started = time.monotonic()
    for index in range(len(reports), args.count):
        level, profile = profiles[index % len(profiles)]
        child_output = output.with_name(f"{output.stem}-{index + 1:02d}.json")
        # Persist progress before the expensive child audit starts.  This makes
        # a stuck generation visible and leaves a resumable diagnostic record.
        output.write_text(json.dumps({
            "status": "running",
            "completed": len(reports),
            "requested": args.count,
            "current": {"cohort_index": index + 1, "level": level, "profile": profile,
                        "started_at": time.time(), "timeout_seconds": args.timeout},
            "reports": reports,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        command = [
            sys.executable,
            str(ROOT / "backend/scripts/audit_cross_level_generation.py"),
            "--level", level,
            "--profile", profile,
            "--jurisdiction", "KZ",
            "--variants", *args.variants,
            "--output", str(child_output),
        ]
        try:
            child_env = os.environ.copy()
            # Keep native BLAS/tokenizer runtimes bounded across the long
            # sequence of disposable ML audits.  This prevents thread-pool
            # exhaustion and Windows access violations without changing model
            # weights or scoring semantics.
            child_env.update({
                "OMP_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "TORCH_NUM_THREADS": "1",
                "TOKENIZERS_PARALLELISM": "false",
            })
            run_kwargs = {
                "cwd": ROOT,
                "env": child_env,
                "text": True,
                "capture_output": True,
                "timeout": args.timeout,
            }
            # A native Windows crash in the disposable child must not open a
            # modal "python.exe" dialog that blocks the whole cohort.  Retry
            # once because the audit is isolated and idempotent; a persistent
            # failure is still recorded in the cohort report.
            if os.name == "nt":
                run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            attempts = 2
            completed = None
            for attempt in range(attempts):
                completed = subprocess.run(command, **run_kwargs)
                if completed.returncode == 0 or attempt == attempts - 1:
                    break
            report = json.loads(child_output.read_text(encoding="utf-8")) if child_output.exists() else {}
            report["cohort_index"] = index + 1
            report["process_returncode"] = completed.returncode
            report["process_attempts"] = attempt + 1
            if completed.returncode != 0:
                report["stderr_tail"] = completed.stderr[-2000:]
        except Exception as exc:  # keep the cohort moving and record the failure
            report = {"cohort_index": index + 1, "level": level, "profile": profile, "passed": False, "error": repr(exc)}
        reports.append(report)
        output.write_text(json.dumps({"status": "running", "completed": len(reports), "requested": args.count, "reports": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = [row for row in reports if row.get("passed") is True]
    summary = {
        "status": "complete",
        "requested": args.count,
        "completed": len(reports),
        "passed": len(passed),
        "failed": len(reports) - len(passed),
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "by_level_profile": {
            f"{level}/{profile}": {
                "count": sum(1 for row in reports if row.get("level") == level and row.get("profile") == profile),
                "passed": sum(1 for row in passed if row.get("level") == level and row.get("profile") == profile),
            }
            for level, profile in profiles
        },
        "reports": reports,
    }
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("status", "requested", "completed", "passed", "failed", "elapsed_seconds")}, ensure_ascii=False))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
