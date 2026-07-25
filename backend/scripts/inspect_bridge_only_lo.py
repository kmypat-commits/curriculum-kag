"""Read-only report for LOs supported only by bridge modules."""

from __future__ import annotations

import argparse
import json

from audit_control_programs_api import login, request_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--variant", default="A")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    token = login(args.base_url)
    sources = request_json(
        f"{args.base_url}/planner/{args.version}/lo-coverage-sources?variant={args.variant}",
        token,
    )
    preview = request_json(
        f"{args.base_url}/planner/{args.version}/bridge-replacement-preview?variant={args.variant}",
        token,
    )
    bridge_only = [row for row in sources.get("items", []) if row.get("status") == "bridge_supported"]
    bridge_ids = {
        source.get("bridge_module_id")
        for row in bridge_only
        for source in row.get("bridge_sources", [])
    }
    suggestions = [
        row for row in preview.get("suggestions", [])
        if row.get("bridge_module_id") in bridge_ids or row.get("bridge_item_id") in bridge_ids
    ]
    print(json.dumps({
        "summary": sources.get("summary", {}),
        "bridge_only": bridge_only,
        "replacement_suggestions": suggestions,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
