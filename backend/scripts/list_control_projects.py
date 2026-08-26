"""List saved projects suitable for cross-level planner regression."""

from __future__ import annotations

import json
import argparse
import sys

from audit_control_programs_api import login, request_json


if hasattr(sys.stdout, "reconfigure"):
    # The script is also used from legacy Windows PowerShell consoles where
    # the active CP1251 code page cannot print Kazakh characters.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int)
    args = parser.parse_args()
    base_url = "http://127.0.0.1:8000"
    token = login(base_url)
    payload = request_json(f"{base_url}/projects/", token)
    projects = payload if isinstance(payload, list) else payload.get("items", [])
    result = []
    for project in projects:
        if args.id and int(project.get("id")) != args.id:
            continue
        detail = request_json(f"{base_url}/projects/{project.get('id')}", token)
        constraints = detail.get("constraints") or {}
        result.append({
            "id": project.get("id"),
            "title": project.get("title"),
            "version_id": (detail.get("latest_version") or {}).get("id"),
            "level": constraints.get("education_level"),
            "credits": constraints.get("total_credits"),
            "jurisdiction": constraints.get("jurisdiction"),
            "track": constraints.get("master_track") or constraints.get("doctorate_track"),
            "group": constraints.get("group_code"),
            "constraints": constraints if args.id else None,
        })
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
