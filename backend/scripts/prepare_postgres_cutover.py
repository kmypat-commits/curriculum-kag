"""Prepare a safe SQLite -> PostgreSQL primary cutover report.

The script is intentionally read-only. It does not edit .env, does not stop
services, and does not mutate SQLite/PostgreSQL. It checks the local evidence
that should exist before switching Curriculum-KAG from SQLite/auto mode to a
PostgreSQL primary runtime.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import socket
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPARE = ROOT / ".runtime" / "sqlite-postgres-counts-valid.json"
DEFAULT_SQLITE = ROOT / "backend" / "curriculum_kag.db"


def sqlite_quick_check(path: Path, deep: bool = False) -> str:
    if not path.exists():
        return "missing"
    if not deep:
        size = path.stat().st_size
        return f"exists:{size}"
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as db:
        return str(db.execute("PRAGMA quick_check").fetchone()[0])


def load_compare(path: Path) -> dict:
    if not path.exists():
        return {"passed": False, "missing": True, "path": str(path)}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return {"passed": False, "invalid_json": str(exc), "path": str(path)}


def check_http(url: str, timeout: int = 5) -> dict:
    socket.setdefaulttimeout(timeout)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return {"url": url, "ok": 200 <= response.status < 300, "status": response.status}
    except URLError as exc:
        return {"url": url, "ok": False, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--compare-json", type=Path, default=DEFAULT_COMPARE)
    parser.add_argument("--postgres-url", default="postgresql+psycopg2://curriculum_user:curriculum_pass@localhost:5433/curriculum_kag_shadow")
    parser.add_argument("--backend-health", default="http://127.0.0.1:8000/health")
    parser.add_argument("--frontend-health", default="http://127.0.0.1:3001/api/health")
    parser.add_argument("--health-timeout", type=int, default=3)
    parser.add_argument(
        "--deep-sqlite-check",
        action="store_true",
        help="Run PRAGMA quick_check on the 12GB SQLite database. This can take a long time.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    sqlite_check = sqlite_quick_check(args.sqlite, deep=args.deep_sqlite_check)
    compare = load_compare(args.compare_json)
    backend = check_http(args.backend_health, timeout=args.health_timeout)
    frontend = check_http(args.frontend_health, timeout=args.health_timeout)

    gates = {
        "sqlite_available": sqlite_check == "ok" or sqlite_check.startswith("exists:"),
        "sqlite_quick_check_ok": sqlite_check == "ok" if args.deep_sqlite_check else None,
        "postgres_count_compare_ok": bool(compare.get("passed")),
        "backend_health_ok": bool(backend.get("ok")),
        "frontend_health_ok": bool(frontend.get("ok")),
    }
    required_gates = {key: value for key, value in gates.items() if value is not None}
    ready = all(required_gates.values())
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ready_for_cutover": ready,
        "gates": gates,
        "sqlite": {
            "path": str(args.sqlite),
            "quick_check": sqlite_check,
        },
        "postgres": {
            "url_hint": args.postgres_url.replace("curriculum_pass", "***"),
            "compare_json": str(args.compare_json),
            "compare_passed": bool(compare.get("passed")),
            "table_count": len(compare.get("tables") or []),
        },
        "live_health": {
            "backend": backend,
            "frontend": frontend,
        },
        "cutover_commands": [
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\stop.ps1",
            ".\\start.ps1 -Database postgres-shadow",
        ],
        "rollback_commands": [
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\stop.ps1",
            ".\\start.ps1 -Database sqlite",
        ],
        "decision": (
            "Можно запускать в PostgreSQL shadow/primary mode после ручного подтверждения backup."
            if ready else
            "Переход откладывается: один или несколько gate не прошли."
        ),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
