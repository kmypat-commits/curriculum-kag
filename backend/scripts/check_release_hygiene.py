"""Fail fast when repository-only releases contain local secrets or artefacts."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_TRACKED_BYTES = 50 * 1024 * 1024
SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{20,})"
)
FORBIDDEN_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".pth", ".pt", ".safetensors", ".onnx"}
FORBIDDEN_PARTS = ("/backend/models/", "/experiment-results/", "/backups/", "/.runtime/")


def tracked_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    )
    return [ROOT / value for value in result.stdout.decode("utf-8").split("\0") if value]


def main() -> int:
    failures: list[str] = []
    for path in tracked_paths():
        # During a local move Git still lists the source path until the next
        # commit.  A deleted path cannot be published, so assess only files
        # that are present in the worktree.
        if not path.exists():
            continue
        relative = path.relative_to(ROOT).as_posix()
        lower = f"/{relative.lower()}"
        name = path.name.lower()
        if name in {".env", ".env.local", ".env.production"}:
            failures.append(f"secret environment file tracked: {relative}")
        if name.endswith(tuple(FORBIDDEN_SUFFIXES)) or any(part in lower for part in FORBIDDEN_PARTS):
            failures.append(f"local artefact tracked: {relative}")
        if path.is_file() and path.stat().st_size > MAX_TRACKED_BYTES:
            failures.append(f"tracked file exceeds 50 MiB: {relative}")
        if path.is_file() and path.suffix.lower() in {".py", ".js", ".jsx", ".ps1", ".yml", ".yaml", ".md"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if SECRET_RE.search(text):
                failures.append(f"possible secret in tracked text: {relative}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"release hygiene passed ({len(tracked_paths())} tracked paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
