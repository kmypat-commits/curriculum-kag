"""Train an EPVO reranker with verified within-programme in-batch negatives."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

import torch
from sentence_transformers import InputExample, SentenceTransformer, losses
from torch.utils.data import DataLoader


LANGUAGES = ("ru", "kz", "en")


def localized(value: dict, language: str) -> str:
    order = (language, *(item for item in LANGUAGES if item != language))
    return next((str(value.get(item) or "").strip() for item in order if value.get(item)), "")


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def course_text(course: dict, language: str) -> str:
    return " | ".join(
        filter(
            None,
            (
                localized(course.get("title") or {}, language),
                localized(course.get("description") or {}, language),
            ),
        )
    )


def pair_key(left: str, right: str) -> bytes:
    return hashlib.sha1(
        normalize(left).encode("utf-8") + b"\0" + normalize(right).encode("utf-8")
    ).digest()


def programme_batches(path: Path, pair_limit: int, batch_size: int, seed: int, language: str):
    """Reservoir-sample induced matchings from train-programme expert graphs.

    For every two selected edges (course_i, LO_i) and (course_j, LO_j), both
    cross-pairs are verified absent from the programme's declared expert links.
    Therefore in-batch negatives are programme-relevant without contradicting a
    known positive label.
    """
    rng = random.Random(seed)
    batch_limit = pair_limit // batch_size
    reservoir: list[list[InputExample]] = []
    seen_global_pairs: set[bytes] = set()
    eligible_batches = 0
    stats = {
        "train_programmes": 0,
        "programmes_with_batches": 0,
        "declared_edges": 0,
        "eligible_batches": 0,
        "selected_batches": 0,
        "selected_pairs": 0,
        "duplicate_pairs_skipped": 0,
        "cross_positive_rejections": 0,
        "incomplete_groups_skipped": 0,
        "batch_size": batch_size,
        "language": language,
        "sampling": "reservoir of within-programme induced matchings",
    }
    with path.open(encoding="utf-8") as source:
        for line in source:
            program = json.loads(line)
            if program.get("split") != "train":
                continue
            stats["train_programmes"] += 1
            courses = {str(item["id"]): item for item in program.get("courses") or []}
            outcomes = {str(item["id"]): item for item in program.get("outcomes") or []}
            edges = {
                (str(course_id), str(outcome_id))
                for course_id, outcome_id in program.get("positive_edges") or []
                if str(course_id) in courses and str(outcome_id) in outcomes
            }
            stats["declared_edges"] += len(edges)
            candidates = list(edges)
            rng.shuffle(candidates)
            programme_had_batch = False
            while candidates:
                selected: list[tuple[str, str, str, str, bytes]] = []
                deferred: list[tuple[str, str]] = []
                used_courses: set[str] = set()
                used_outcomes: set[str] = set()
                used_texts: set[str] = set()
                for course_id, outcome_id in candidates:
                    left = course_text(courses[course_id], language)
                    right = localized(outcomes[outcome_id].get("text") or {}, language)
                    key = pair_key(left, right) if left and right else b""
                    text_keys = {normalize(left), normalize(right)}
                    cross_positive = any(
                        (course_id, other_outcome) in edges or (other_course, outcome_id) in edges
                        for other_course, other_outcome, *_ in selected
                    )
                    valid = (
                        left
                        and right
                        and key not in seen_global_pairs
                        and course_id not in used_courses
                        and outcome_id not in used_outcomes
                        and used_texts.isdisjoint(text_keys)
                        and not cross_positive
                    )
                    if valid and len(selected) < batch_size:
                        selected.append((course_id, outcome_id, left, right, key))
                        used_courses.add(course_id)
                        used_outcomes.add(outcome_id)
                        used_texts.update(text_keys)
                    else:
                        deferred.append((course_id, outcome_id))
                        if key and key in seen_global_pairs:
                            stats["duplicate_pairs_skipped"] += 1
                        if cross_positive:
                            stats["cross_positive_rejections"] += 1
                if len(selected) < batch_size:
                    stats["incomplete_groups_skipped"] += 1
                    break
                programme_had_batch = True
                for *_, key in selected:
                    seen_global_pairs.add(key)
                batch = [InputExample(texts=[left, right], label=1.0) for _, _, left, right, _ in selected]
                eligible_batches += 1
                if len(reservoir) < batch_limit:
                    reservoir.append(batch)
                else:
                    position = rng.randrange(eligible_batches)
                    if position < batch_limit:
                        reservoir[position] = batch
                candidates = deferred
            if programme_had_batch:
                stats["programmes_with_batches"] += 1
    rng.shuffle(reservoir)
    stats["eligible_batches"] = eligible_batches
    stats["selected_batches"] = len(reservoir)
    stats["selected_pairs"] = len(reservoir) * batch_size
    return [row for batch in reservoir for row in batch], stats


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
    parser.add_argument("--output", default="models/epvo-sbert-program-ranker-8k")
    parser.add_argument("--pairs", type=int, default=8000)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--mini-batch-size", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=5e-7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--language", choices=LANGUAGES, default="ru")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.pairs < args.batch_size or args.pairs % args.batch_size:
        raise ValueError("--pairs must be divisible by --batch-size")

    output = Path(args.output)
    progress = output.with_name(output.name + "-progress.json")
    common = {
        "model": args.model,
        "output": args.output,
        "requested_pairs": args.pairs,
        "batch_size": args.batch_size,
        "mini_batch_size": args.mini_batch_size,
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "seed": args.seed,
        "directions": ["query_to_doc", "doc_to_query"],
        "negative_policy": "same programme; both cross-pairs absent from declared expert links",
    }
    write_progress(progress, "preparing", **common)
    rows, stats = programme_batches(
        Path(args.input), args.pairs, args.batch_size, args.seed, args.language
    )
    prepared = {**common, "selected_pairs": len(rows), "sampling": stats}
    write_progress(progress, "prepared", **prepared)
    if args.dry_run:
        print(json.dumps({"status": "dry_run_complete", **prepared}, ensure_ascii=False, indent=2))
        return
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if len(rows) < args.batch_size:
        raise RuntimeError("No complete programme-aware batches were produced")

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

    loader = DataLoader(rows, batch_size=args.batch_size, shuffle=False, drop_last=True)
    objective = losses.CachedMultipleNegativesRankingLoss(
        model,
        mini_batch_size=args.mini_batch_size,
        directions=("query_to_doc", "doc_to_query"),
        partition_mode="per_direction",
        show_progress_bar=False,
    )
    write_progress(progress, "training", **prepared, cuda=torch.cuda.get_device_name(0))
    model.fit(
        train_objectives=[(loader, objective)],
        epochs=args.epochs,
        warmup_steps=max(10, len(loader) // 10),
        optimizer_params={"lr": args.learning_rate},
        use_amp=True,
        checkpoint_path=str(output.with_name(output.name + "-checkpoints")),
        checkpoint_save_steps=max(200, len(loader) // 2),
        checkpoint_save_total_limit=2,
        output_path=str(output),
        show_progress_bar=True,
    )
    result = {
        **prepared,
        "cuda": torch.cuda.get_device_name(0),
        "loss": "CachedMultipleNegativesRankingLoss",
    }
    write_progress(progress, "complete", **result)
    print(json.dumps({"status": "complete", **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
