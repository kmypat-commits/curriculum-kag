"""Fill missing EPVO translations with the already cached local NLLB model.

Only empty normalized fields are changed. Every generated value is tagged as a
machine draft, so it is never presented as expert-verified evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from sqlalchemy import create_engine, text


LANGS = {"ru": "rus_Cyrl", "kk": "kaz_Cyrl", "en": "eng_Latn"}


def repair_mojibake(value: str) -> str:
    """Recover UTF-8 text that was decoded as CP1251, conservatively."""
    value = " ".join(str(value or "").split()).strip()
    def score(text_value: str) -> int:
        return len(re.findall(r"[\u0420\u0421][\u0410-\u042f\u0401\u0430-\u044f\u0490-\u04ff]", text_value)) + sum(text_value.count(ch) for ch in ("\u2122", "\u00a4", "\u0403", "\u040e", "\u0402"))
    for _ in range(3):
        if score(value) < 2:
            break
        try:
            candidate = value.encode("cp1251").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if score(candidate) >= score(value):
            break
        value = candidate
    return value


def model_path() -> str:
    root = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    base = root / "hub" / "models--facebook--nllb-200-distilled-600M" / "snapshots"
    candidates = [p for p in base.glob("*") if (p / "config.json").exists() and ((p / "model.safetensors").exists() or (p / "pytorch_model.bin").exists())]
    if not candidates:
        raise FileNotFoundError("Cached NLLB model not found; refusing to download it")
    return str(sorted(candidates)[-1])


def translate_batch(tokenizer, model, texts: list[str], source: str, target: str, device: str, max_new_tokens: int) -> list[str]:
    import torch

    tokenizer.src_lang = source
    encoded = tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=512).to(device)
    forced = tokenizer.convert_tokens_to_ids(target)
    with torch.inference_mode():
        generated = model.generate(**encoded, forced_bos_token_id=forced, max_new_tokens=max_new_tokens, num_beams=1)
    return [repair_mojibake(x) for x in tokenizer.batch_decode(generated, skip_special_tokens=True)]


def apply_items(engine, items: list[dict]) -> None:
    """Commit one generated batch so long runs can be resumed safely."""
    if not items:
        return
    with engine.begin() as conn:
        for item in items:
            row = conn.execute(text("select content_json,approved_course_id from epvo_disciplines_normalized where id=:id for update"), {"id": item["id"]}).mappings().one()
            content = row["content_json"] if isinstance(row["content_json"], dict) else {}
            key = f"description_{item['language']}" if item["field"] == "description" else None
            if item["field"] == "title":
                conn.execute(text(f"update epvo_disciplines_normalized set title_{item['language']}=:v where id=:id and length(btrim(coalesce(title_{item['language']},'')))=0"), {"v": item["value"], "id": item["id"]})
            else:
                if str(content.get(key) or "").strip():
                    continue
                content[key] = item["value"]
                meta = content.get("translation_provenance") if isinstance(content.get("translation_provenance"), dict) else {}
                meta[item["language"]] = "machine_nllb_draft"
                content["translation_provenance"] = meta
                conn.execute(text("update epvo_disciplines_normalized set content_json=cast(:c as jsonb) where id=:id"), {"c": json.dumps(content, ensure_ascii=False), "id": item["id"]})
            if row["approved_course_id"]:
                if item["field"] == "title":
                    conn.execute(text("update course_localizations set title=:v,source='machine_nllb_draft',status='needs_review',updated_at=now() where course_id=:cid and language=:lang and length(btrim(coalesce(title,'')))=0"), {"v": item["value"], "cid": row["approved_course_id"], "lang": item["language"]})
                else:
                    conn.execute(text("update course_localizations set description=:v,source='machine_nllb_draft',status='needs_review',updated_at=now() where course_id=:cid and language=:lang and length(btrim(coalesce(description,'')))=0"), {"v": item["value"], "cid": row["approved_course_id"], "lang": item["language"]})


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--database-url", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--limit", type=int, default=0, help="0 means all missing fields")
    p.add_argument("--apply", action="store_true", help="write drafts; without it only translates a preview")
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--max-new-tokens", type=int, default=128)
    args = p.parse_args()

    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    path = model_path()
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(path, local_files_only=True).to(device).eval()
    engine = create_engine(args.database_url, future=True)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            select id, approved_course_id, title_ru, title_kk, title_en, content_json
            from epvo_disciplines_normalized
            where length(btrim(coalesce(title_kk,'')))=0
               or length(btrim(coalesce(title_en,'')))=0
               or length(btrim(coalesce(content_json->>'description_ru','')))=0
               or length(btrim(coalesce(content_json->>'description_kk','')))=0
               or length(btrim(coalesce(content_json->>'description_en','')))=0
            order by id
        """)).mappings().all()

    tasks: list[tuple[int, str, str, str, str]] = []
    for row in rows:
        content = row["content_json"] if isinstance(row["content_json"], dict) else {}
        ru_title = str(row["title_ru"] or "").strip()
        descriptions = {lang: repair_mojibake(str(content.get(f"description_{lang}") or "")) for lang in LANGS}
        source_desc = next(((lang, value) for lang, value in descriptions.items() if value), None)
        if not ru_title and not source_desc:
            continue
        for lang in LANGS:
            if not str(row[f"title_{lang}"] or "").strip() and ru_title:
                tasks.append((row["id"], lang, "title", ru_title, "rus_Cyrl"))
            if not descriptions[lang] and source_desc:
                source_lang, source_text = source_desc
                if source_lang != lang:
                    tasks.append((row["id"], lang, "description", source_text, LANGS[source_lang]))
    if args.limit:
        tasks = tasks[: args.limit]

    results: list[dict] = []
    for start in range(0, len(tasks), args.batch_size):
        batch = tasks[start : start + args.batch_size]
        for lang in LANGS:
            for source_code in sorted({task[4] for task in batch if task[1] == lang}):
                indices = [i for i, task in enumerate(batch) if task[1] == lang and task[4] == source_code]
                if not indices:
                    continue
                values = translate_batch(tokenizer, model, [batch[i][3] for i in indices], source_code, LANGS[lang], device, args.max_new_tokens)
                for i, value in zip(indices, values):
                    row_id, out_lang, field, source, _source_code = batch[i]
                    results.append({"id": row_id, "language": out_lang, "field": field, "source": source, "value": value, "source_language": source_code})
        if args.apply:
            apply_items(engine, results[-len(batch) * len(LANGS):])

    if False and args.apply and results:
        with engine.begin() as conn:
            for item in results:
                row = conn.execute(text("select content_json,approved_course_id from epvo_disciplines_normalized where id=:id for update"), {"id": item["id"]}).mappings().one()
                content = row["content_json"] if isinstance(row["content_json"], dict) else {}
                key = f"description_{item['language']}" if item["field"] == "description" else None
                if item["field"] == "title":
                    conn.execute(text(f"update epvo_disciplines_normalized set title_{item['language']}=:v where id=:id and length(btrim(coalesce(title_{item['language']},'')))=0"), {"v": item["value"], "id": item["id"]})
                else:
                    content[key] = item["value"]
                    meta = content.get("translation_provenance") if isinstance(content.get("translation_provenance"), dict) else {}
                    meta[item["language"]] = "machine_nllb_draft"
                    content["translation_provenance"] = meta
                    conn.execute(text("update epvo_disciplines_normalized set content_json=cast(:c as jsonb) where id=:id"), {"c": json.dumps(content, ensure_ascii=False), "id": item["id"]})
                if row["approved_course_id"]:
                    if item["field"] == "title":
                        conn.execute(text("update course_localizations set title=:v,source='machine_nllb_draft',status='needs_review',updated_at=now() where course_id=:cid and language=:lang and length(btrim(coalesce(title,'')))=0"), {"v": item["value"], "cid": row["approved_course_id"], "lang": item["language"]})
                    else:
                        conn.execute(text("update course_localizations set description=:v,source='machine_nllb_draft',status='needs_review',updated_at=now() where course_id=:cid and language=:lang and length(btrim(coalesce(description,'')))=0"), {"v": item["value"], "cid": row["approved_course_id"], "lang": item["language"]})

    payload = {"model": path, "device": device, "tasks": len(tasks), "generated": len(results), "applied": bool(args.apply), "preview": results[:10]}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("device", "tasks", "generated", "applied")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
