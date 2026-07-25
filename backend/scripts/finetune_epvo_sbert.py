"""Fine-tune local multilingual SBERT on leakage-safe EPVO course–LO pairs."""
from __future__ import annotations

import argparse
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import InputExample, SentenceTransformer, losses
from torch.utils.data import DataLoader


def text(value):
    return value.get("ru") or value.get("kz") or value.get("en") or ""


def words(value):
    return set(re.findall(r"\w+", value.casefold()))


def overlap(left, right):
    a, b = words(left), words(right)
    return len(a & b) / max(1, len(a | b))


def examples(path, limit, seed=42, hard_negative_ratio=0.75, mining_model=None):
    rng = random.Random(seed)
    rows = []
    stats = {"positive": 0, "random_negative": 0, "hard_negative": 0}
    with path.open(encoding="utf-8") as source:
        for line in source:
            program = json.loads(line)
            if program.get("split") != "train":
                continue
            courses = {str(item["id"]): item for item in program["courses"]}
            outcomes = {str(item["id"]): item for item in program["outcomes"]}
            edges = {(str(course), str(outcome)) for course, outcome in program["positive_edges"]}
            linked = {}
            for course, outcome in edges:
                linked.setdefault(course, set()).add(outcome)
            semantic_course_vectors = {}
            semantic_outcome_vectors = {}
            if mining_model is not None:
                eligible_courses = [course for course in linked if course in courses]
                outcome_ids = list(outcomes)
                course_texts = [
                    text(courses[course]["title"]) + ". " + text(courses[course]["description"])
                    for course in eligible_courses
                ]
                if course_texts and outcome_ids:
                    course_vectors = mining_model.encode(
                        course_texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False
                    )
                    outcome_vectors = mining_model.encode(
                        [text(outcomes[outcome]["text"]) for outcome in outcome_ids],
                        batch_size=32,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                    semantic_course_vectors = dict(zip(eligible_courses, course_vectors))
                    semantic_outcome_vectors = dict(zip(outcome_ids, outcome_vectors))
            for course_id, positives in linked.items():
                negatives = [outcome for outcome in outcomes if outcome not in positives]
                if course_id not in courses or not negatives:
                    continue
                course = text(courses[course_id]["title"]) + ". " + text(courses[course_id]["description"])
                positive = rng.choice(sorted(positives))
                if rng.random() < hard_negative_ratio:
                    if mining_model is None:
                        negative = max(negatives, key=lambda item: overlap(course, text(outcomes[item]["text"])))
                    else:
                        course_vector = semantic_course_vectors[course_id]
                        negative_vectors = np.stack([semantic_outcome_vectors[item] for item in negatives])
                        similarities = negative_vectors @ course_vector
                        negative = negatives[int(similarities.argmax())]
                    stats["hard_negative"] += 1
                else:
                    negative = rng.choice(negatives)
                    stats["random_negative"] += 1
                rows.append(InputExample(texts=[course, text(outcomes[positive]["text"])], label=1.0))
                rows.append(InputExample(texts=[course, text(outcomes[negative]["text"])], label=0.0))
                stats["positive"] += 1
                if len(rows) >= limit:
                    rng.shuffle(rows)
                    return rows, stats
    rng.shuffle(rows)
    return rows, stats


def write_progress(path, status, **extra):
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
    parser.add_argument("--model", default="models/paraphrase-multilingual-mpnet-base-v2")
    parser.add_argument("--output", default="models/epvo-sbert-finetuned-pilot")
    parser.add_argument("--examples", type=int, default=8000)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--hard-negative-ratio", type=float, default=0.75)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--semantic-mining", action="store_true")
    parser.add_argument("--loss", choices=("cosine", "multiple-negatives"), default="cosine")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    progress = Path(args.output).with_name(Path(args.output).name + "-progress.json")
    write_progress(progress, "preparing", examples=args.examples, hard_negative_ratio=args.hard_negative_ratio)
    mining_model = None
    if args.semantic_mining:
        mining_model = SentenceTransformer(args.model, device="cuda" if torch.cuda.is_available() else "cpu", local_files_only=True)
    rows, stats = examples(
        Path(args.input),
        args.examples,
        args.seed,
        args.hard_negative_ratio,
        mining_model=mining_model,
    )
    del mining_model
    write_progress(
        progress,
        "prepared",
        examples=len(rows),
        sampling=stats,
        mining="semantic" if args.semantic_mining else "lexical",
    )
    if args.dry_run:
        effective = sum(item.label > 0 for item in rows) if args.loss == "multiple-negatives" else len(rows)
        print(json.dumps({"status": "dry_run_complete", "examples": len(rows), "effective_examples": effective, "sampling": stats, "loss": args.loss}, ensure_ascii=False))
        return
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this training script")

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

    training_rows = [item for item in rows if item.label > 0] if args.loss == "multiple-negatives" else rows
    loader = DataLoader(training_rows, shuffle=True, batch_size=args.batch_size)
    loss = (
        losses.MultipleNegativesRankingLoss(model)
        if args.loss == "multiple-negatives"
        else losses.CosineSimilarityLoss(model)
    )
    write_progress(
        progress,
        "training",
        examples=len(rows),
        effective_examples=len(training_rows),
        sampling=stats,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        loss=args.loss,
        cuda=torch.cuda.get_device_name(0),
    )
    model.fit(
        train_objectives=[(loader, loss)],
        epochs=args.epochs,
        warmup_steps=max(10, len(loader) // 10),
        optimizer_params={"lr": args.learning_rate},
        use_amp=True,
        checkpoint_path=str(Path(args.output).with_name(Path(args.output).name + "-checkpoints")),
        checkpoint_save_steps=500,
        checkpoint_save_total_limit=2,
        output_path=args.output,
        show_progress_bar=True,
    )
    result = {
        "status": "complete",
        "examples": len(rows),
        "effective_examples": len(training_rows),
        "sampling": stats,
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "loss": args.loss,
        "output": args.output,
        "cuda": torch.cuda.get_device_name(0),
    }
    write_progress(progress, **result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
