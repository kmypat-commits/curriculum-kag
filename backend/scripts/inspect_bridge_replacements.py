"""Read-only compact preview of bridge replacement candidates."""

from __future__ import annotations

import argparse
import json
import sys

from audit_control_programs_api import login, request_json


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--variant", default="A")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    base_url = "http://127.0.0.1:8000"
    token = login(base_url)
    data = request_json(
        f"{base_url}/planner/{args.version}/bridge-replacement-preview?variant={args.variant}",
        token,
    )
    suggestions = data.get("suggestions", [])
    compact = [{
        "bridge_item_id": row.get("bridge_item_id"),
        "bridge_title": row.get("bridge_title"),
        "target_los": row.get("target_los", []),
        "strong": [
            {
                "course_id": candidate.get("course_id"),
                "title": candidate.get("title"),
                "model_score": candidate.get("model_score"),
                "expert_score": candidate.get("expert_score"),
                "coverage_ratio": candidate.get("coverage_ratio"),
                "credit_distance": candidate.get("credit_distance"),
            }
            for candidate in row.get("candidates", [])
            if candidate.get("strong_candidate")
        ],
    } for row in suggestions]
    print(json.dumps({
        "variant": args.variant,
        "bridges": len(suggestions),
        "replaceable": sum(1 for row in compact if row["strong"]),
        "suggestions": suggestions if args.full else compact,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
