"""Audit translation parity, mojibake, and user-visible hardcoded English."""
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRANSLATIONS = ROOT / "frontend" / "src" / "translations.js"


def translation_keys(text, language, next_language=None):
    start = text.index(f"    {language}: {{")
    end = text.index(f"    {next_language}: {{", start) if next_language else text.rindex("    }")
    section = text[start:end]
    return set(re.findall(r"(?:^|[,\n])\s*([A-Za-z_][A-Za-z0-9_]*):", section))


def main():
    source = TRANSLATIONS.read_text(encoding="utf-8")
    keys = {
        "ru": translation_keys(source, "ru", "kk"),
        "kk": translation_keys(source, "kk", "en"),
        "en": translation_keys(source, "en"),
    }
    generated_kk_path = ROOT / "frontend" / "src" / "translations_kk_generated.json"
    generated_kk = set(json.loads(generated_kk_path.read_text(encoding="utf-8"))) if generated_kk_path.exists() else set()
    keys["kk"] |= generated_kk
    all_keys = set.union(*keys.values())
    missing = {lang: sorted(all_keys - values) for lang, values in keys.items()}
    mojibake = []
    hardcoded = []
    for path in [ROOT / "frontend" / "src", ROOT / "backend" / "app"]:
        for file in path.rglob("*"):
            if file.suffix not in {".js", ".jsx", ".py", ".css"}:
                continue
            text = file.read_text(encoding="utf-8", errors="replace")
            for line_no, line in enumerate(text.splitlines(), 1):
                if re.search(r"Р[ђЃѓ°±‚ђµЅРЎ]|С[ѓ‚Њ‹]|вЂ|в†|рџ", line):
                    mojibake.append({"file": str(file.relative_to(ROOT)), "line": line_no})
                if file.suffix == ".jsx" and "Curriculum KAG" not in line and re.search(r">\s*[A-Z][A-Za-z ]{3,}\s*<|placeholder=[\"'][A-Z]", line):
                    hardcoded.append({"file": str(file.relative_to(ROOT)), "line": line_no, "text": line.strip()[:180]})
    report = {
        "translation_key_counts": {lang: len(values) for lang, values in keys.items()},
        "missing_keys": missing,
        "mojibake_count": len(mojibake), "mojibake": mojibake,
        "hardcoded_english_count": len(hardcoded), "hardcoded_english": hardcoded,
    }
    output = ROOT / "backend" / "experiment-results" / "localization-audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output), "key_counts": report["translation_key_counts"],
        "missing": {lang: len(value) for lang, value in missing.items()},
        "mojibake": len(mojibake), "hardcoded_english": len(hardcoded),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
