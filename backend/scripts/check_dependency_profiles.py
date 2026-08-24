"""Verify that local and Docker dependency profiles use one compatible baseline.

The local profile may omit deliberately optional packages (currently FAISS),
but every package shared with the Docker profile must have exactly the same
version.  This is intentionally dependency-free so it can run before pip.
"""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s#]+)$")


def read_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = PIN.match(line)
        if not match:
            raise ValueError(f"{path.name}:{number}: dependency must use an exact == pin: {raw}")
        name = match.group(1).lower().replace("_", "-")
        pins[name] = match.group(2)
    return pins


def main() -> int:
    production = read_pins(ROOT / "requirements.txt")
    local = read_pins(ROOT / "requirements-local.txt")
    lock = read_pins(ROOT / "requirements.lock")
    missing = sorted(name for name in local if name not in production)
    mismatches = sorted(
        f"{name}: local {version}, Docker {production[name]}"
        for name, version in local.items()
        if name in production and production[name] != version
    )
    lock_mismatches = sorted(
        f"{name}: lock {lock.get(name)}, production {version}"
        for name, version in production.items()
        if lock.get(name) != version
    )
    lock_missing = sorted(name for name in production if name not in lock)
    if missing or mismatches or lock_mismatches or lock_missing:
        if missing:
            print("Local-only packages without a Docker decision: " + ", ".join(missing))
        if mismatches:
            print("Version mismatches: " + "; ".join(mismatches))
        if lock_missing:
            print("Production packages missing from requirements.lock: " + ", ".join(lock_missing))
        if lock_mismatches:
            print("Lock mismatches: " + "; ".join(lock_mismatches))
        return 1
    optional = sorted(set(production) - set(local))
    print(
        f"Dependency profiles are compatible: {len(local)} shared exact pins and {len(lock)} locked pins; "
        f"Docker-only optional packages: {', '.join(optional) or 'none'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
