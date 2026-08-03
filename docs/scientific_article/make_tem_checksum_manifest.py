"""Create a reproducibility checksum manifest for the TEM submission package."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = [
    "TEM_official_template.docx",
    "Curriculum_KAG_TEM_manuscript_official_template.docx",
    "Curriculum_KAG_TEM_manuscript_anonymous.docx",
    "TEM_SUPPLEMENTARY_MATERIALS_EN.md",
    "TEM_FROZEN_RESULTS_TABLE_EN.md",
    "TEM_COVER_LETTER_EN.md",
    "TEM_SUBMISSION_CHECKLIST_EN.md",
    "tem_package_audit.json",
    "tem_anonymity_audit.json",
    "TEM_UPLOAD_INSTRUCTIONS_RU.md",
    "tem_text_audit.json",
    "tem_citation_audit.json",
    "TEM_READINESS_REPORT_RU.md",
]

manifest = {
    "algorithm": "SHA-256",
    "files": [],
}
for name in FILES:
    path = ROOT / name
    data = path.read_bytes()
    manifest["files"].append({
        "path": name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    })

(ROOT / "TEM_CHECKSUM_MANIFEST.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
