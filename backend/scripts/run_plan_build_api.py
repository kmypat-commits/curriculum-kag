"""Run a plan build through the local API and save a compact result.

Intended for long local verification runs. Credentials can be overridden with
CURRICULUM_LOCAL_EMAIL and CURRICULUM_LOCAL_PASSWORD.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def request_json(url: str, *, data: bytes | None = None, token: str | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=1800) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_version_id", type=int)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    email = os.getenv("CURRICULUM_LOCAL_EMAIL", "admin@curriculum-kag.local")
    password = os.getenv("CURRICULUM_LOCAL_PASSWORD", "admin123")
    login_data = urllib.parse.urlencode({"username": email, "password": password}).encode()
    started = time.perf_counter()
    result: dict
    try:
        login = request_json(f"{args.base_url}/auth/login", data=login_data)
        token = login["access_token"]
        build_request = urllib.request.Request(
            f"{args.base_url}/planner/{args.project_version_id}/build",
            data=b"",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            method="POST",
        )
        with urllib.request.urlopen(build_request, timeout=1800) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result = {
            "ok": True,
            "project_version_id": args.project_version_id,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "variants": {
                key: {
                    "plan_id": value.get("plan_id"),
                    "total_credits": value.get("metrics", {}).get("total_credits"),
                    "courses": value.get("metrics", {}).get("total_courses"),
                    "bridges": value.get("metrics", {}).get("num_bridge_modules"),
                    "min_lo_coverage": value.get("metrics", {}).get("min_lo_coverage"),
                    "hard_violations": value.get("verification", {}).get("hard_violation_count"),
                }
                for key, value in payload.get("variants", {}).items()
            },
        }
    except urllib.error.HTTPError as exc:
        result = {
            "ok": False,
            "project_version_id": args.project_version_id,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "status": exc.code,
            "error": exc.read().decode("utf-8", errors="replace")[:2000],
        }
    except Exception as exc:  # keep a durable status for unattended runs
        result = {
            "ok": False,
            "project_version_id": args.project_version_id,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "error": str(exc),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
