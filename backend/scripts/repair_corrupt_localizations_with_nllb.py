"""Repair question-mark-corrupted course descriptions from clean EN text.

The repair is deliberately conservative: only descriptions containing a run
of three or more literal question marks are changed.  Existing clean English
is translated with the already cached local NLLB model and stored as a machine
draft requiring expert review.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from sqlalchemy import create_engine, text

LANGS = {"ru": "rus_Cyrl", "kk": "kaz_Cyrl", "en": "eng_Latn"}
CORRUPT = re.compile(r"\?{3,}")


def model_path() -> str:
    root = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    base = root / "hub" / "models--facebook--nllb-200-distilled-600M" / "snapshots"
    candidates = [p for p in base.glob("*") if (p / "config.json").exists()]
    if not candidates:
        raise FileNotFoundError("Cached NLLB model not found; refusing to download")
    return str(sorted(candidates)[-1])


def translate_batch(tokenizer, model, texts, source, target, device):
    import torch
    tokenizer.src_lang = source
    encoded = tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=512).to(device)
    forced = tokenizer.convert_tokens_to_ids(target)
    with torch.inference_mode():
        generated = model.generate(**encoded, forced_bos_token_id=forced, max_new_tokens=160, num_beams=1)
    return tokenizer.batch_decode(generated, skip_special_tokens=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    import torch

    engine = create_engine(args.database_url, future=True)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            select course_id, language, description
            from course_localizations
            where description ~ '\\?{3,}'
            order by course_id, language
        """)).mappings().all()
        course_ids = sorted({int(row["course_id"]) for row in rows})
        clean_en = {
            int(row["course_id"]): str(row["description"] or "").strip()
            for row in conn.execute(text("""
                select course_id, description from course_localizations
                where language='en' and description is not null
                  and description !~ '\\?{3,}'
            """)).mappings().all()
            if str(row["description"] or "").strip()
        }

    tasks = [(course_id, lang, clean_en[course_id])
             for course_id in course_ids if course_id in clean_en
             for lang in ("ru", "kk")]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(model_path(), local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_path(), local_files_only=True).to(device).eval()
    generated = []
    for start in range(0, len(tasks), args.batch_size):
        batch = tasks[start:start + args.batch_size]
        for lang in ("ru", "kk"):
            indexes = [i for i, task in enumerate(batch) if task[1] == lang]
            if not indexes:
                continue
            values = translate_batch(tokenizer, model, [batch[i][2] for i in indexes], LANGS["en"], LANGS[lang], device)
            generated.extend({"course_id": batch[i][0], "language": lang, "value": value.strip()} for i, value in zip(indexes, values))

    applied = 0
    if args.apply:
        with engine.begin() as conn:
            for item in generated:
                result = conn.execute(text("""
                    update course_localizations
                    set description=:value, source='machine_nllb_repair', status='needs_review', updated_at=now()
                    where course_id=:course_id and language=:language and description ~ '\\?{3,}'
                """), item)
                applied += int(result.rowcount or 0)
    report = {"device": device, "corrupt_courses": len(course_ids), "tasks": len(tasks), "generated": len(generated), "applied": applied, "model": model_path()}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
