"""Train a leakage-safe EPVO reranker with cached in-batch negatives.

The production SBERT 40k model is used only as initialization and is never
overwritten. Training examples come exclusively from the programme-level train
split. Exact duplicate course/LO texts are excluded from every virtual batch to
reduce false in-batch negatives.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import torch
from sentence_transformers import InputExample, SentenceTransformer, losses
from torch.utils.data import DataLoader, Sampler


LANGUAGE_ORDER = ("ru", "kz", "en")


def localized(value: dict, language: str = "ru") -> str:
    order = (language, *(item for item in LANGUAGE_ORDER if item != language))
    return next((str(value.get(item) or "").strip() for item in order if value.get(item)), "")


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def digest(value: str) -> bytes:
    return hashlib.sha1(normalized(value).encode("utf-8")).digest()


def course_text(course: dict, language: str) -> str:
    return " | ".join(
        item
        for item in (
            localized(course.get("title") or {}, language),
            localized(course.get("description") or {}, language),
        )
        if item
    )


def positive_pairs(path: Path, limit: int, seed: int, language: str):
    """Uniformly sample unique positive pairs from all train programmes."""
    rng = random.Random(seed)
    reservoir: list[InputExample] = []
    seen_pairs: set[bytes] = set()
    stats = {
        "train_programmes": 0,
        "declared_edges": 0,
        "eligible_unique_pairs": 0,
        "duplicate_pairs_skipped": 0,
        "empty_pairs_skipped": 0,
        "language": language,
        "sampling": "uniform reservoir over train programmes",
    }
    with path.open(encoding="utf-8") as source:
        for line in source:
            program = json.loads(line)
            if program.get("split") != "train":
                continue
            stats["train_programmes"] += 1
            courses = {str(item["id"]): item for item in program.get("courses") or []}
            outcomes = {str(item["id"]): item for item in program.get("outcomes") or []}
            for course_id, outcome_id in program.get("positive_edges") or []:
                stats["declared_edges"] += 1
                course = courses.get(str(course_id))
                outcome = outcomes.get(str(outcome_id))
                if not course or not outcome:
                    stats["empty_pairs_skipped"] += 1
                    continue
                left = course_text(course, language)
                right = localized((outcome.get("text") or {}), language)
                if not left or not right:
                    stats["empty_pairs_skipped"] += 1
                    continue
                pair_key = hashlib.sha1(
                    normalized(left).encode("utf-8") + b"\0" + normalized(right).encode("utf-8")
                ).digest()
                if pair_key in seen_pairs:
                    stats["duplicate_pairs_skipped"] += 1
                    continue
                seen_pairs.add(pair_key)
                stats["eligible_unique_pairs"] += 1
                example = InputExample(texts=[left, right], label=1.0)
                if len(reservoir) < limit:
                    reservoir.append(example)
                else:
                    position = rng.randrange(stats["eligible_unique_pairs"])
                    if position < limit:
                        reservoir[position] = example
    rng.shuffle(reservoir)
    stats["selected_pairs"] = len(reservoir)
    return reservoir, stats


class NoDuplicateTextBatchSampler(Sampler[list[int]]):
    """Yield batches without repeated text in either column."""

    def __init__(self, rows: list[InputExample], batch_size: int, seed: int):
        self.rows = rows
        self.batch_size = batch_size
        self.seed = seed
        self.iteration = 0
        self.keys = [(digest(row.texts[0]), digest(row.texts[1])) for row in rows]

    def __len__(self) -> int:
        return math.ceil(len(self.rows) / self.batch_size)

    def __iter__(self):
        rng = random.Random(self.seed + self.iteration)
        self.iteration += 1
        order = list(range(len(self.rows)))
        rng.shuffle(order)
        pending = deque(order)
        while pending:
            batch: list[int] = []
            used: set[bytes] = set()
            blocked = 0
            while pending and len(batch) < self.batch_size:
                index = pending.popleft()
                row_keys = self.keys[index]
                if used.isdisjoint(row_keys):
                    batch.append(index)
                    used.update(row_keys)
                    blocked = 0
                else:
                    pending.append(index)
                    blocked += 1
                    if blocked >= len(pending):
                        break
            if len(batch) >= 2:
                yield batch
            elif batch:
                # A single pair has no in-batch negative and is intentionally omitted.
                continue
            else:
                break


def write_progress(path: Path, status: str, **extra) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), **extra},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiment-results/epvo-link-context-dataset/programs.jsonl")
    parser.add_argument("--model", default="models/epvo-sbert-finetuned-40k")
    parser.add_argument("--output", default="models/epvo-sbert-cached-ranker-12k")
    parser.add_argument("--pairs", type=int, default=12000)
    parser.add_argument("--virtual-batch-size", type=int, default=32)
    parser.add_argument("--mini-batch-size", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=5e-7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--language", choices=LANGUAGE_ORDER, default="ru")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    progress = output.with_name(output.name + "-progress.json")
    common = {
        "model": args.model,
        "output": args.output,
        "requested_pairs": args.pairs,
        "virtual_batch_size": args.virtual_batch_size,
        "mini_batch_size": args.mini_batch_size,
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "seed": args.seed,
        "directions": ["query_to_doc", "doc_to_query"],
        "false_negative_guard": "no exact duplicate text across both batch columns",
    }
    write_progress(progress, "preparing", **common)
    rows, stats = positive_pairs(Path(args.input), args.pairs, args.seed, args.language)
    sampler = NoDuplicateTextBatchSampler(rows, args.virtual_batch_size, args.seed)
    safe_batches = list(sampler)
    batch_sizes = [len(batch) for batch in safe_batches]
    preparation = {
        **common,
        "selected_pairs": len(rows),
        "batches": len(batch_sizes),
        "min_batch": min(batch_sizes, default=0),
        "max_batch": max(batch_sizes, default=0),
        "sampling": stats,
    }
    write_progress(progress, "prepared", **preparation)
    if args.dry_run:
        print(json.dumps({"status": "dry_run_complete", **preparation}, ensure_ascii=False, indent=2))
        return
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this training script")
    if len(rows) < args.virtual_batch_size:
        raise RuntimeError("Not enough unique positive pairs for one virtual batch")

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

    # SentenceTransformers 5.x fit adapter requires DataLoader.batch_size to be
    # an integer. Pre-order one-epoch training rows using the duplicate-safe
    # sampler, then expose a standard fixed-size DataLoader to the adapter.
    ordered_rows = [rows[index] for batch in safe_batches for index in batch]
    loader = DataLoader(
        ordered_rows,
        batch_size=args.virtual_batch_size,
        shuffle=False,
        drop_last=True,
    )
    objective = losses.CachedMultipleNegativesRankingLoss(
        model,
        mini_batch_size=args.mini_batch_size,
        directions=("query_to_doc", "doc_to_query"),
        partition_mode="per_direction",
        show_progress_bar=False,
    )
    write_progress(
        progress,
        "training",
        **preparation,
        cuda=torch.cuda.get_device_name(0),
    )
    model.fit(
        train_objectives=[(loader, objective)],
        epochs=args.epochs,
        warmup_steps=max(10, len(loader) // 10),
        optimizer_params={"lr": args.learning_rate},
        use_amp=True,
        checkpoint_path=str(output.with_name(output.name + "-checkpoints")),
        checkpoint_save_steps=max(100, len(loader) // 2),
        checkpoint_save_total_limit=2,
        output_path=str(output),
        show_progress_bar=True,
    )
    result = {
        **preparation,
        "cuda": torch.cuda.get_device_name(0),
        "loss": "CachedMultipleNegativesRankingLoss",
    }
    write_progress(progress, "complete", **result)
    print(json.dumps({"status": "complete", **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
