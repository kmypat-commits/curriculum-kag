"""Mine expert-safe hard triplets and train an EPVO LO-to-course reranker."""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import InputExample, SentenceTransformer, losses
from torch.utils.data import DataLoader


LANGUAGES = ("ru", "kz", "en")


def localized(value: dict, language: str = "ru") -> str:
    order = (language, *(item for item in LANGUAGES if item != language))
    return next((str(value.get(item) or "").strip() for item in order if value.get(item)), "")


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


def programme_sample(path: Path, limit: int, seed: int):
    """Deterministically retain train programmes with the lowest hashes."""
    selected = []
    counter = 0
    with path.open(encoding="utf-8") as source:
        for line in source:
            program = json.loads(line)
            if program.get("split") != "train":
                continue
            key = int.from_bytes(
                hashlib.sha256(
                    f"mined-triplets-v1:{seed}:{program['program_id']}".encode()
                ).digest(),
                "big",
            )
            item = (-key, counter, program)
            counter += 1
            if len(selected) < limit:
                heapq.heappush(selected, item)
            elif item[0] > selected[0][0]:
                heapq.heapreplace(selected, item)
    selected.sort(key=lambda item: -item[0])
    return [program for _, _, program in selected]


def mine(
    programmes: list[dict],
    model: SentenceTransformer,
    pair_limit: int,
    language: str,
    output: Path,
):
    rows: list[InputExample] = []
    records = []
    stats = {
        "programmes_selected": len(programmes),
        "programmes_used": 0,
        "outcomes_seen": 0,
        "triples_mined": 0,
        "no_negative_skipped": 0,
        "empty_text_skipped": 0,
        "negative_policy": "highest-scoring unlinked course in the same train programme",
    }
    for program in programmes:
        courses = {str(item["id"]): item for item in program.get("courses") or []}
        outcomes = {str(item["id"]): item for item in program.get("outcomes") or []}
        edges = {
            (str(course_id), str(outcome_id))
            for course_id, outcome_id in program.get("positive_edges") or []
            if str(course_id) in courses and str(outcome_id) in outcomes
        }
        linked = {}
        for course_id, outcome_id in edges:
            linked.setdefault(outcome_id, set()).add(course_id)
        course_ids = [key for key, value in courses.items() if course_text(value, language)]
        outcome_ids = [
            key
            for key, value in outcomes.items()
            if key in linked and localized(value.get("text") or {}, language)
        ]
        if len(course_ids) < 2 or not outcome_ids:
            continue
        course_texts = [course_text(courses[key], language) for key in course_ids]
        outcome_texts = [localized(outcomes[key].get("text") or {}, language) for key in outcome_ids]
        course_vectors = model.encode(
            course_texts, batch_size=48, normalize_embeddings=True, show_progress_bar=False
        )
        outcome_vectors = model.encode(
            outcome_texts, batch_size=48, normalize_embeddings=True, show_progress_bar=False
        )
        scores = np.asarray(outcome_vectors) @ np.asarray(course_vectors).T
        used = False
        for lo_index, outcome_id in enumerate(outcome_ids):
            stats["outcomes_seen"] += 1
            positive_ids = linked[outcome_id]
            positives = [
                index for index, course_id in enumerate(course_ids) if course_id in positive_ids
            ]
            negatives = [
                index for index, course_id in enumerate(course_ids) if course_id not in positive_ids
            ]
            if not positives or not negatives:
                stats["no_negative_skipped"] += 1
                continue
            # Train against the hardest currently known false candidate. Pair it
            # with the least confidently ranked declared positive to correct the
            # most consequential ordering error first.
            positive_index = min(positives, key=lambda index: scores[lo_index, index])
            negative_index = max(negatives, key=lambda index: scores[lo_index, index])
            query = outcome_texts[lo_index]
            positive = course_texts[positive_index]
            negative = course_texts[negative_index]
            if not query or not positive or not negative:
                stats["empty_text_skipped"] += 1
                continue
            rows.append(InputExample(texts=[query, positive, negative], label=1.0))
            records.append(
                {
                    "program_id": str(program["program_id"]),
                    "lo_id": outcome_id,
                    "positive_course_id": course_ids[positive_index],
                    "negative_course_id": course_ids[negative_index],
                    "positive_score_before": float(scores[lo_index, positive_index]),
                    "negative_score_before": float(scores[lo_index, negative_index]),
                    "margin_before": float(
                        scores[lo_index, positive_index] - scores[lo_index, negative_index]
                    ),
                }
            )
            used = True
            if len(rows) >= pair_limit:
                break
        if used:
            stats["programmes_used"] += 1
        if len(rows) >= pair_limit:
            break
    stats["triples_mined"] = len(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as target:
        for record in records:
            target.write(json.dumps(record, ensure_ascii=False) + "\n")
    return rows, stats


def progress(path: Path, status: str, **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), **extra},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiment-results/epvo-link-context-dataset/programs.jsonl")
    parser.add_argument("--model", default="models/epvo-sbert-ranking-loss-pilot")
    parser.add_argument("--output", default="models/epvo-sbert-mined-triplets-6k")
    parser.add_argument("--triples", type=int, default=6000)
    parser.add_argument("--programmes", type=int, default=1200)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--mini-batch-size", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-7)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--language", choices=LANGUAGES, default="ru")
    parser.add_argument("--mine-only", action="store_true")
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")

    output = Path(args.output)
    status_path = output.with_name(output.name + "-progress.json")
    triples_path = output.with_name(output.name + "-triples.jsonl")
    common = {
        "model": args.model,
        "output": args.output,
        "requested_triples": args.triples,
        "programme_limit": args.programmes,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "seed": args.seed,
    }
    progress(status_path, "selecting_programmes", **common)
    programmes = programme_sample(Path(args.input), args.programmes, args.seed)
    model = SentenceTransformer(args.model, device="cuda", local_files_only=True)
    progress(status_path, "mining", **common, selected_programmes=len(programmes))
    rows, stats = mine(
        programmes, model, args.triples, args.language, triples_path
    )
    prepared = {**common, "mining": stats, "triples_file": str(triples_path)}
    progress(status_path, "mined", **prepared)
    if args.mine_only:
        print(json.dumps({"status": "mine_complete", **prepared}, ensure_ascii=False))
        return
    if len(rows) < args.batch_size:
        raise RuntimeError("Not enough mined triples")

    model.max_seq_length = 192
    transformer = model[0].auto_model
    transformer.gradient_checkpointing_enable()
    if hasattr(transformer, "embeddings"):
        for parameter in transformer.embeddings.parameters():
            parameter.requires_grad = False
    layers = getattr(getattr(transformer, "encoder", None), "layer", [])
    for layer in list(layers)[:8]:
        for parameter in layer.parameters():
            parameter.requires_grad = False
    loader = DataLoader(rows, shuffle=True, batch_size=args.batch_size, drop_last=True)
    objective = losses.CachedMultipleNegativesRankingLoss(
        model,
        mini_batch_size=args.mini_batch_size,
        directions=("query_to_doc",),
        hardness_mode="hard_negatives",
        hardness_strength=1.0,
        show_progress_bar=False,
    )
    progress(status_path, "training", **prepared, cuda=torch.cuda.get_device_name(0))
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
        "loss": "CachedMultipleNegativesRankingLoss with explicit hard negatives",
    }
    progress(status_path, "complete", **result)
    print(json.dumps({"status": "complete", **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
