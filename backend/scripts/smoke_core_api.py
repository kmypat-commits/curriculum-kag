"""Read-only smoke test for the UI's critical plan-analysis endpoints.

The default check never invokes an external LLM.  Use ``--include-ai`` only
when intentionally verifying the optional provider-backed LO analysis.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request_json(url: str, *, method: str = "GET", headers: dict | None = None, payload: dict | None = None) -> tuple[int, bytes, object]:
    """Make a small JSON/form request without optional runtime packages."""
    request_headers = dict(headers or {})
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:  # nosec B310: local operator-supplied URL
            content = response.read()
            return response.status, content, json.loads(content.decode("utf-8")) if content else None
    except HTTPError as exc:
        content = exc.read()
        detail = content.decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"{method} {url} returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach {url}: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--project-version-id", type=int)
    parser.add_argument(
        "--max-read-ms",
        type=int,
        default=5000,
        help="fail if one read-only plan endpoint exceeds this latency budget",
    )
    parser.add_argument(
        "--include-ai",
        action="store_true",
        help="also call the optional provider-backed LO-achievability analysis",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    login_body = urlencode({"username": "admin@curriculum-kag.local", "password": "admin123"}).encode("utf-8")
    login_request = Request(
        f"{base}/auth/login",
        data=login_body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(login_request, timeout=60) as response:  # nosec B310: local operator-supplied URL
            login_payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"login failed: {exc}") from exc
    token = login_payload.get("access_token")
    if not token:
        raise RuntimeError("login response did not contain access_token")
    headers = {"Authorization": f"Bearer {token}"}

    version_id = args.project_version_id
    if version_id is None:
        _status, _content, payload = request_json(f"{base}/projects", headers=headers)
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
            try:
                _status, _content, detail_payload = request_json(f"{base}/projects/{row['id']}", headers=headers)
            except RuntimeError:
                continue
            latest = detail_payload.get("latest_version") or {}
            if latest.get("id"):
                version_id = latest["id"]
                break
    if not version_id:
        raise RuntimeError("project has no latest version")

    _status, _content, health = request_json(f"{base}/health")
    if health.get("status") != "healthy":
        raise RuntimeError("health endpoint did not report healthy")

    request_json(f"{base}/repository/stats", headers=headers)

    checks = [
        ("build-status", "GET", f"{base}/planner/{version_id}/build-status"),
        ("variants", "GET", f"{base}/planner/{version_id}/variants"),
        ("evaluation", "GET", f"{base}/planner/{version_id}/evaluation"),
        ("graph", "GET", f"{base}/planner/version/{version_id}/graph?variant=A"),
    ]
    if args.include_ai:
        checks.append(("lo-achievability", "POST", f"{base}/kag/{version_id}/lo-achievability"))
    for name, method, url in checks:
        started = time.perf_counter()
        status, content, _payload = request_json(
            url, method=method, headers=headers, payload={"language": "ru"} if method == "POST" else None
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        if not content:
            raise RuntimeError(f"{name} returned an empty response")
        if elapsed_ms > args.max_read_ms:
            raise RuntimeError(f"{name} exceeded {args.max_read_ms} ms: {elapsed_ms} ms")
        print(f"PASS {name}: HTTP {status}, {len(content)} bytes, {elapsed_ms} ms")
    print("PASS core API smoke: read-only checks completed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL core API smoke: {exc}", file=sys.stderr)
        raise SystemExit(1)
