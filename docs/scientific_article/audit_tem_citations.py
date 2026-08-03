"""Check that every numbered citation in the DOCX has a matching reference."""
from pathlib import Path
import json
import re
from docx import Document

ROOT = Path(__file__).resolve().parent
text = "\n".join(p.text for p in Document(ROOT / "Curriculum_KAG_TEM_manuscript_official_template.docx").paragraphs)
cited = set(map(int, re.findall(r"\[(\d+)\]", text)))
listed = set(map(int, re.findall(r"^\[(\d+)\]", text, flags=re.M)))
result = {
    "cited_numbers": sorted(cited),
    "listed_numbers": sorted(listed),
    "missing_references": sorted(cited - listed),
    "uncited_references": sorted(listed - cited),
    "pass": cited == listed and bool(cited),
}
(ROOT / "tem_citation_audit.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False, indent=2))
if not result["pass"]:
    raise SystemExit(1)
