"""Fail the local quality gate when executable source contains mojibake."""
from __future__ import annotations

import re
from pathlib import Path


PAIR_PATTERN = re.compile(r"[РС][\u0400-\u04ff]")
CYRILLIC_PATTERN = re.compile(r"[\u0400-\u04ff]")
DIRECT_MARKERS = ("вЂ", "вњ", "рџ", "�")
LATIN1_MARKERS = ("Ð", "Ñ")
SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".css", ".ps1"}


def looks_like_mojibake(text: str) -> bool:
    if any(marker in text for marker in DIRECT_MARKERS):
        return True
    if sum(text.count(marker) for marker in LATIN1_MARKERS) >= 2:
        return True
    cyrillic = CYRILLIC_PATTERN.findall(text)
    pairs = PAIR_PATTERN.findall(text)
    return len(pairs) >= 3 and len(pairs) / max(1, len(cyrillic)) >= 0.18


def source_files(repository_root: Path):
    roots = (
        repository_root / "backend" / "app",
        repository_root / "frontend" / "src",
    )
    for root in roots:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS:
                yield path
    for name in ("start.ps1", "stop.ps1", "test.ps1", "smoke-test.ps1"):
        path = repository_root / name
        if path.exists():
            yield path


def scan_repository(repository_root: Path) -> list[str]:
    problems: list[str] = []
    for path in source_files(repository_root):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            problems.append(f"{path}: invalid UTF-8 ({exc})")
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            # The planner deliberately recognises these marker characters
            # when repairing historical database text.
            if 'suspicious = "Ð" in' in line:
                continue
            if looks_like_mojibake(line):
                problems.append(f"{path}:{line_number}: suspicious mojibake")
    return problems


def main() -> int:
    repository_root = Path(__file__).resolve().parents[1]
    problems = scan_repository(repository_root)
    if problems:
        print("Text encoding gate failed:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("Text encoding gate: UTF-8 source is clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
