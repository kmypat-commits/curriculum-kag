"""Check generated TEM manuscripts for replacement characters and common mojibake."""
from pathlib import Path
import json
from docx import Document

ROOT = Path(__file__).resolve().parent
files = [
    "Curriculum_KAG_TEM_manuscript_official_template.docx",
    "Curriculum_KAG_TEM_manuscript_anonymous.docx",
]
bad_tokens = ("вЂ", "Р“", "Рќ", "â€", "Ã")
result = {}
for name in files:
    text = "\n".join(p.text for p in Document(ROOT / name).paragraphs)
    result[name] = {
        "replacement_characters": text.count("�"),
        "mojibake_tokens": sum(text.count(token) for token in bad_tokens),
        "characters": len(text),
    }
result["pass"] = all(
    v["replacement_characters"] == 0 and v["mojibake_tokens"] == 0
    for v in result.values() if isinstance(v, dict)
)
(ROOT / "tem_text_audit.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False, indent=2))
if not result["pass"]:
    raise SystemExit(1)
