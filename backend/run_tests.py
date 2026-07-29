"""Dependency-free test runner for the project's plain-assert test suite."""
from __future__ import annotations

import importlib
import inspect
import sys
import traceback
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main() -> int:
    test_dir = BACKEND_DIR / "tests"
    modules = [
        importlib.import_module(f"tests.{path.stem}")
        for path in sorted(test_dir.glob("test_*.py"))
    ]
    tests = [
        (f"{module.__name__}.{name}", function)
        for module in modules
        for name, function in inspect.getmembers(module, inspect.isfunction)
        if name.startswith("test_")
    ]
    failures = []
    for name, function in tests:
        try:
            function()
            print(f"PASS {name}")
        except Exception:
            failures.append(name)
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\nResult: {len(tests) - len(failures)}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
