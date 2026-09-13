"""Reconcile an orphaned quality-cohort report without rerunning the cohort."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_quality_cohort import reconcile_running_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    result = reconcile_running_report(args.report.resolve())
    if result is None:
        print(json.dumps({"status": "unavailable", "report": str(args.report)}, ensure_ascii=False))
        return 2
    print(json.dumps({
        "status": result.get("status"),
        "run_id": result.get("run_id"),
        "stale_reason": result.get("stale_reason"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
