"""Batch-translate unmatched repository titles; output remains machine_draft."""
import json
import os
import re
import sqlite3
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "curriculum_kag.db"
OUTPUT = ROOT / "backend" / "data" / "course_translations.json"
MODEL = "facebook/nllb-200-distilled-600M"
LANG = {"ru": "rus_Cyrl", "en": "eng_Latn", "kk": "kaz_Cyrl"}


def detected_language(title, declared):
    latin = len(re.findall(r"[A-Za-z]", title or ""))
    cyrillic = len(re.findall(r"[А-Яа-яӘәІіҢңҒғҮүҰұҚқӨөҺһ]", title or ""))
    if latin > cyrillic * 2:
        return "en"
    if cyrillic > latin * 2:
        return "kk" if declared in {"kk", "kz"} else "ru"
    return "kk" if declared in {"kk", "kz"} else (declared or "ru")


def main():
    data = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    with sqlite3.connect(DB) as db:
        rows = db.execute("SELECT id,title,language FROM courses ORDER BY id").fetchall()
    pending = [(row[0], row[1], detected_language(row[1], row[2])) for row in rows if data.get(str(row[0]), {}).get("review_status") not in {"verified_epvo", "verified_epvo_fuzzy", "approved"}]
    tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL, local_files_only=True, dtype=torch.float16 if torch.cuda.is_available() else torch.float32).to("cuda" if torch.cuda.is_available() else "cpu")
    for source in ("ru", "en", "kk"):
        source_rows = [row for row in pending if ("kk" if row[2] in {"kk", "kz"} else row[2]) == source]
        for target in LANG:
            if target == source:
                continue
            tokenizer.src_lang = LANG[source]
            for offset in range(0, len(source_rows), 32):
                batch_rows = source_rows[offset:offset + 32]
                values = [row[1] for row in batch_rows]
                if not values:
                    continue
                encoded = tokenizer(values, return_tensors="pt", padding=True, truncation=True, max_length=96)
                encoded = {key: value.to(model.device) for key, value in encoded.items()}
                with torch.inference_mode():
                    generated = model.generate(**encoded, forced_bos_token_id=tokenizer.convert_tokens_to_ids(LANG[target]), max_length=112)
                translated = tokenizer.batch_decode(generated, skip_special_tokens=True)
                for row, value in zip(batch_rows, translated):
                    record = data.setdefault(str(row[0]), {"review_status": "machine_draft", "source_language": source, "title": {}})
                    record["review_status"] = "machine_draft"
                    record.setdefault("title", {})[source] = row[1]
                    record["title"][target] = value
                OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"translated_titles": len(pending), "device": str(model.device)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
