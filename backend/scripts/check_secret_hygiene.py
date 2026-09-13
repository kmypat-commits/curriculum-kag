"""Fail closed when tracked files contain common credential material."""

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}"),
)
ALLOWED_NAMES = {".env.example", ".env.production.example"}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    return [ROOT / item for item in result.stdout.decode().split("\0") if item]


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        if path.name in ALLOWED_NAMES or not path.is_file():
            continue
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in PATTERNS):
            findings.append(str(path.relative_to(ROOT)))
    if findings:
        print("Tracked credential-like material found:")
        print("\n".join(sorted(findings)))
        return 1
    print("Secret hygiene gate passed: no credential signatures in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
