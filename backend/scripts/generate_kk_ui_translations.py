"""Fill missing Kazakh UI strings with the local NLLB model."""
import ast
import json
import re
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "frontend" / "src" / "translations.js"
OUTPUT = ROOT / "frontend" / "src" / "translations_kk_generated.json"
MODEL = "facebook/nllb-200-distilled-600M"


def section(text, language, next_language=None):
    start = text.index(f"    {language}: {{")
    end = text.index(f"    {next_language}: {{", start) if next_language else text.rindex("    }")
    return text[start:end]


def strings(text):
    result = {}
    pattern = re.compile(r"(?:^|[,\n])\s*([A-Za-z_][A-Za-z0-9_]*):\s*('(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")")
    for key, value in pattern.findall(text):
        try:
            result[key] = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            continue
    return result


def main():
    text = SOURCE.read_text(encoding="utf-8")
    ru = strings(section(text, "ru", "kk"))
    kk = strings(section(text, "kk", "en"))
    missing = {key: value for key, value in ru.items() if key not in kk}
    existing = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    pending = [(key, value) for key, value in missing.items() if key not in existing]
    if not pending:
        print(json.dumps({"generated": 0, "total": len(existing)}))
        return
    tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    tokenizer.src_lang = "rus_Cyrl"
    model = AutoModelForSeq2SeqLM.from_pretrained(
        MODEL, local_files_only=True,
        dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    ).to("cuda" if torch.cuda.is_available() else "cpu")
    for offset in range(0, len(pending), 24):
        batch_rows = pending[offset:offset + 24]
        values = [value for _, value in batch_rows]
        batch = tokenizer(values, return_tensors="pt", padding=True, truncation=True, max_length=192)
        batch = {name: tensor.to(model.device) for name, tensor in batch.items()}
        with torch.inference_mode():
            generated = model.generate(
                **batch,
                forced_bos_token_id=tokenizer.convert_tokens_to_ids("kaz_Cyrl"),
                max_length=220,
            )
        translations = tokenizer.batch_decode(generated, skip_special_tokens=True)
        existing.update({key: value for (key, _), value in zip(batch_rows, translations)})
        OUTPUT.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"done": min(offset + len(batch_rows), len(pending)), "pending": len(pending)}), flush=True)
    print(json.dumps({"generated": len(pending), "total": len(existing)}))


if __name__ == "__main__":
    main()
