"""Fine-tune SBERT with EPVO external-expert soft labels.

Labels are the mean external-expert assessment for a course--LO pair.  The
loss therefore sees 0 (rejected), 0.5 (medium), and 1 (high), instead of
collapsing every declared link to a binary positive.  Programme-level splits
are read from the export and only ``train`` rows are used for fitting.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import torch
from sentence_transformers import InputExample, SentenceTransformer, losses
from torch.utils.data import DataLoader


def text(value: dict) -> str:
    return value.get("ru") or value.get("kz") or value.get("en") or ""


def write_progress(path: Path, status: str, **extra: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), **extra}, ensure_ascii=False, indent=2), encoding="utf-8")


def reservoir(path: Path, limit: int, seed: int) -> tuple[list[InputExample], dict[str, int]]:
    rng = random.Random(seed)
    rows: list[InputExample] = []
    counts = {"train_labeled": 0, "score_0": 0, "score_0_5": 0, "score_1": 0, "other_mean": 0}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("split") != "train" or row.get("expert_score") is None:
                continue
            score = float(row["expert_score"])
            left = text(row.get("course_title") or {}) + ". " + text(row.get("course_description") or {})
            right = text(row.get("lo_text") or {})
            if not left.strip() or not right.strip():
                continue
            counts["train_labeled"] += 1
            if score == 0:
                counts["score_0"] += 1
            elif score == 0.5:
                counts["score_0_5"] += 1
            elif score == 1:
                counts["score_1"] += 1
            else:
                counts["other_mean"] += 1
            example = InputExample(texts=[left, right], label=max(0.0, min(1.0, score)))
            if len(rows) < limit:
                rows.append(example)
            else:
                index = rng.randrange(counts["train_labeled"])
                if index < limit:
                    rows[index] = example
    rng.shuffle(rows)
    return rows, counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=".runtime/epvo-weighted-postgres/course_lo_pairs.jsonl")
    ap.add_argument("--model", default="backend/models/epvo-sbert-finetuned-40k")
    ap.add_argument("--output", default="backend/models/epvo-sbert-weighted-expert-pilot")
    ap.add_argument("--examples", type=int, default=120000)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--learning-rate", type=float, default=1e-5)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    output = Path(args.output)
    progress = output.with_name(output.name + "-progress.json")
    write_progress(progress, "preparing", input=args.input, examples=args.examples)
    rows, counts = reservoir(Path(args.input), args.examples, args.seed)
    write_progress(progress, "prepared", examples=len(rows), counts=counts)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the weighted SBERT pilot")
    model = SentenceTransformer(args.model, device="cuda", local_files_only=True)
    model.max_seq_length = 192
    transformer = model[0].auto_model
    transformer.gradient_checkpointing_enable()
    if hasattr(transformer, "embeddings"):
        for parameter in transformer.embeddings.parameters():
            parameter.requires_grad = False
    layers = getattr(getattr(transformer, "encoder", None), "layer", [])
    for layer in list(layers)[:6]:
        for parameter in layer.parameters():
            parameter.requires_grad = False
    loader = DataLoader(rows, shuffle=True, batch_size=args.batch_size)
    loss = losses.CosineSimilarityLoss(model)
    write_progress(progress, "training", examples=len(rows), counts=counts, epochs=args.epochs, learning_rate=args.learning_rate, cuda=torch.cuda.get_device_name(0))
    model.fit(
        train_objectives=[(loader, loss)],
        epochs=args.epochs,
        warmup_steps=max(10, len(loader) // 10),
        optimizer_params={"lr": args.learning_rate},
        use_amp=True,
        checkpoint_path=str(output.with_name(output.name + "-checkpoints")),
        checkpoint_save_steps=1000,
        checkpoint_save_total_limit=2,
        output_path=str(output),
        show_progress_bar=True,
    )
    result = {"status": "complete", "model": args.model, "output": str(output), "examples": len(rows), "counts": counts, "epochs": args.epochs, "learning_rate": args.learning_rate, "loss": "CosineSimilarityLoss with soft expert labels", "cuda": torch.cuda.get_device_name(0)}
    write_progress(progress, **result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
