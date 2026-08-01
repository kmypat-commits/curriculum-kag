"""Safely repair UTF-8 text that was decoded once as Windows-1251.

Only writes a file when the reversible transform reduces known mojibake
markers and introduces no replacement characters.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "frontend" / "src", ROOT / "backend" / "app"]
EXTENSIONS = {".js", ".jsx", ".py", ".json"}
MARKERS = ("Р�", "РІ", "РЎ", "Рќ", "Рџ", "Рћ", "Р°", "С", "вЂ", "вњ", "Р”")


def marker_count(value: str) -> int:
    return sum(value.count(marker) for marker in MARKERS)


changed = []
for base in TARGETS:
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix not in EXTENSIONS:
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        before = marker_count(original)
        if before == 0:
            continue
        # JSX/Python files often contain valid Unicode and mojibake on the
        # same line. Repair quoted literals independently rather than applying
        # a lossy transform to the whole source file.
        def repair_literal(match: re.Match[str]) -> str:
            quote, value = match.group(1), match.group(2)
            if marker_count(value) == 0:
                return match.group(0)
            try:
                repaired = value.encode("cp1251").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                return match.group(0)
            if "�" in repaired or marker_count(repaired) >= marker_count(value):
                return match.group(0)
            return quote + repaired + quote

        candidate = re.sub(r"(['\"])([^\n]*?)\1", repair_literal, original)
        if candidate == original or marker_count(candidate) >= before:
            continue
        path.write_text(candidate, encoding="utf-8", newline="")
        changed.append((str(path.relative_to(ROOT)), before, marker_count(candidate)))

print(f"changed={len(changed)}")
for item in changed:
    print(f"{item[0]}: {item[1]} -> {item[2]}")
