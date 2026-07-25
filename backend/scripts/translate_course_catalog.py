"""Create resumable RU/KK/EN translations without changing source records."""
import argparse
import json
import os
import sys
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATABASE_URL"] = os.environ.get(
    "TRANSLATION_DATABASE_URL",
    "sqlite:///" + (Path(__file__).resolve().parents[1] / "curriculum_kag.db").as_posix(),
)

from app.database import SessionLocal
from app.models.course import Course


LANG = {"ru": "rus_Cyrl", "en": "eng_Latn", "kk": "kaz_Cyrl"}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="facebook/nllb-200-distilled-600M")
    parser.add_argument("--output", default="data/course_translations.json")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--local-files-only", action="store_true")
    return parser.parse_args()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main():
    args = parse_args()
    output = Path(args.output)
    data = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=args.local_files_only)
    model = AutoModelForSeq2SeqLM.from_pretrained(
        args.model, local_files_only=args.local_files_only,
        dtype=torch.float16 if torch.cuda.is_available() else torch.float32
    ).to("cuda" if torch.cuda.is_available() else "cpu")
    db = SessionLocal()
    courses = db.query(Course).order_by(Course.id).all()
    if args.limit:
        courses = courses[:args.limit]
    for index, course in enumerate(courses, 1):
        key = str(course.id)
        record = data.setdefault(key, {
            "source_language": course.language or "ru",
            "review_status": "machine_draft",
        })
        record.setdefault("review_status", "machine_draft")
        source = "kk" if course.language in {"kk", "kz"} else (course.language or "ru")
        tokenizer.src_lang = LANG[source]
        fields = {
            "title": course.title,
            "description": course.description or "",
            "topics": course.topics or [],
            "learning_outcomes": course.learning_outcomes or [],
        }
        for field, value in fields.items():
            values = value if isinstance(value, list) else [value]
            translated = record.setdefault(field, {})
            translated[source] = value
            for target in LANG:
                if target == source or target in translated or not any(values):
                    continue
                batch = tokenizer(values, return_tensors="pt", padding=True, truncation=True, max_length=384)
                batch = {name: tensor.to(model.device) for name, tensor in batch.items()}
                with torch.inference_mode():
                    generated = model.generate(**batch, forced_bos_token_id=tokenizer.convert_tokens_to_ids(LANG[target]), max_length=420)
                result = tokenizer.batch_decode(generated, skip_special_tokens=True)
                translated[target] = result if isinstance(value, list) else result[0]
        if index % 10 == 0:
            save(output, data)
            print(f"translated {index}/{len(courses)}", flush=True)
    save(output, data)
    db.close()
    print(f"complete: {len(courses)} courses", flush=True)


if __name__ == "__main__":
    main()
