"""Evaluate a validation-tuned ensemble of two local SBERT models."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics import f1_score

from benchmark_epvo_sbert import metrics, samples


def encode_scores(model, rows, batch_size):
    left = model.encode(
        [row[0] for row in rows],
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    right = model.encode(
        [row[1] for row in rows],
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    return np.sum(left * right, axis=1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiment-results/epvo-link-dataset/programs.jsonl")
    parser.add_argument("--base-model", default="models/epvo-sbert-finetuned-40k")
    parser.add_argument("--candidate-model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=6000)
    parser.add_argument("--batch-size", type=int, default=48)
    parser.add_argument("--device", default="cuda", choices=("cpu", "cuda"))
    args = parser.parse_args()

    source = Path(args.input)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    rows = {split: samples(source, split, args.limit) for split in ("validation", "test")}
    actual = {split: np.asarray([row[2] for row in values]) for split, values in rows.items()}

    base = SentenceTransformer(args.base_model, local_files_only=True, device=args.device)
    base_scores = {split: encode_scores(base, values, args.batch_size) for split, values in rows.items()}
    del base
    candidate = SentenceTransformer(args.candidate_model, local_files_only=True, device=args.device)
    candidate_scores = {split: encode_scores(candidate, values, args.batch_size) for split, values in rows.items()}

    best = None
    for weight in np.linspace(0.0, 1.0, 21):
        validation_scores = (1.0 - weight) * base_scores["validation"] + weight * candidate_scores["validation"]
        thresholds = np.linspace(float(validation_scores.min()), float(validation_scores.max()), 301)
        threshold = max(thresholds, key=lambda value: f1_score(actual["validation"], validation_scores >= value))
        score = f1_score(actual["validation"], validation_scores >= threshold)
        if best is None or score > best["f1"]:
            best = {"candidate_weight": float(weight), "threshold": float(threshold), "f1": float(score)}

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_model": args.base_model,
        "candidate_model": args.candidate_model,
        "selection": "candidate weight and threshold selected on validation only",
        "candidate_weight": best["candidate_weight"],
    }
    for split in ("validation", "test"):
        scores = (
            (1.0 - best["candidate_weight"]) * base_scores[split]
            + best["candidate_weight"] * candidate_scores[split]
        )
        report[split] = metrics(actual[split], scores, best["threshold"])
    (output / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
