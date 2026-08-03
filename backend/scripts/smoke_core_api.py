"""Read-only smoke test for the UI's critical plan-analysis endpoints."""
from __future__ import annotations

import argparse
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--project-version-id", type=int)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    with httpx.Client(timeout=60.0) as client:
        login = client.post(
            f"{base}/auth/login",
            data={"username": "admin@curriculum-kag.local", "password": "admin123"},
        )
        login.raise_for_status()
        token = login.json().get("access_token")
        if not token:
            raise RuntimeError("login response did not contain access_token")
        headers = {"Authorization": f"Bearer {token}"}

        version_id = args.project_version_id
        if version_id is None:
            projects = client.get(f"{base}/projects", headers=headers)
            projects.raise_for_status()
            payload = projects.json()
            rows = payload.get("items", payload) if isinstance(payload, dict) else payload
            if not rows:
                raise RuntimeError("no projects available for smoke test")
            # The list endpoint is intentionally lightweight and may omit the
            # nested latest_version object.  Resolve each project through its
            # detail endpoint instead of treating that omission as a failure.
            for row in rows:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                latest = row.get("latest_version") or {}
                if latest.get("id"):
                    version_id = latest["id"]
                    break
                detail = client.get(f"{base}/projects/{row['id']}", headers=headers)
                if detail.status_code >= 400:
                    continue
                detail_payload = detail.json()
                latest = detail_payload.get("latest_version") or {}
                if latest.get("id"):
                    version_id = latest["id"]
                    break
        if not version_id:
            raise RuntimeError("project has no latest version")

        checks = [
            ("variants", "GET", f"{base}/planner/{version_id}/variants"),
            ("graph", "GET", f"{base}/planner/version/{version_id}/graph?variant=A"),
            ("lo-achievability", "POST", f"{base}/kag/{version_id}/lo-achievability"),
        ]
        for name, method, url in checks:
            response = client.request(
                method,
                url,
                headers=headers,
                json={"language": "ru"} if method == "POST" else None,
            )
            response.raise_for_status()
            if not response.content:
                raise RuntimeError(f"{name} returned an empty response")
            print(f"PASS {name}: HTTP {response.status_code}, {len(response.content)} bytes")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL core API smoke: {exc}", file=sys.stderr)
        raise SystemExit(1)
