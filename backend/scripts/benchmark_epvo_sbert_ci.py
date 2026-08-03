"""Frozen SBERT benchmark with programme-level bootstrap confidence intervals.

This is an offline research script. It does not modify the production model or
database. Predictions are persisted so the reported intervals can be audited.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics import (
    accuracy_score, average_precision_score, f1_score, precision_score,
    recall_score, roc_auc_score,
)


def text(values):
    return values.get("ru") or values.get("kz") or values.get("en") or ""


def rows(path: Path, split: str, limit: int, include_context: bool = False):
    result = []
    with path.open(encoding="utf-8") as stream:
        for program in stream:
            program = json.loads(program)
            if program.get("split") != split:
                continue
            courses = {str(x["id"]): x for x in program["courses"]}
            outcomes = {str(x["id"]): x for x in program["outcomes"]}
            edges = {(str(a), str(b)) for a, b in program["positive_edges"]}
            by_course = {}
            for course_id, lo_id in edges:
                by_course.setdefault(course_id, set()).add(lo_id)
            rng = random.Random(f"{program['program_id']}:sbert:42")
            for course_id, positive_ids in by_course.items():
                if course_id not in courses:
                    continue
                negative_ids = [x for x in outcomes if x not in positive_ids]
                if not negative_ids:
                    continue
                positive_id = rng.choice(sorted(positive_ids))
                negative_id = rng.choice(negative_ids)
                course = courses[course_id]
                context = ""
                if include_context:
                    context = " GOAL: " + text(program.get("program_goal") or {})
                    context += " DIRECTION: " + text(program.get("training_direction") or {})
                    context += " GROUP: " + text(program.get("program_group") or {})
                course_text = text(course["title"]) + ". " + text(course["description"]) + context
                result.append({"program_id": str(program["program_id"]), "course": course_text,
                               "outcome": text(outcomes[positive_id]["text"]), "actual": 1})
                result.append({"program_id": str(program["program_id"]), "course": course_text,
                               "outcome": text(outcomes[negative_id]["text"]), "actual": 0})
                if len(result) >= limit:
                    return result[:limit]
    return result


def pooled_metrics(actual, scores, threshold):
    actual = np.asarray(actual)
    scores = np.asarray(scores)
    predicted = scores >= threshold
    return {
        "examples": int(len(actual)),
        "roc_auc": float(roc_auc_score(actual, scores)),
        "pr_auc": float(average_precision_score(actual, scores)),
        "threshold": float(threshold),
        "accuracy": float(accuracy_score(actual, predicted)),
        "precision": float(precision_score(actual, predicted, zero_division=0)),
        "recall": float(recall_score(actual, predicted, zero_division=0)),
        "f1": float(f1_score(actual, predicted, zero_division=0)),
    }


def bootstrap(groups, threshold, repetitions, seed):
    rng = random.Random(seed)
    keys = sorted(groups)
    metrics = {name: [] for name in ("roc_auc", "pr_auc", "f1", "precision", "recall")}
    for _ in range(repetitions):
        chosen = [keys[rng.randrange(len(keys))] for _ in keys]
        actual = np.concatenate([groups[k][0] for k in chosen])
        scores = np.concatenate([groups[k][1] for k in chosen])
        if len(np.unique(actual)) < 2:
            continue
        row = pooled_metrics(actual, scores, threshold)
        for name in metrics:
            metrics[name].append(row[name])
    return {name: [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]
            for name, values in metrics.items() if values}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=6000)
    parser.add_argument("--batch-size", type=int, default=48)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--repetitions", type=int, default=2000)
    parser.add_argument("--context", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    model = SentenceTransformer(args.model, local_files_only=True, device=args.device)
    stored = {}
    for split in ("validation", "test"):
        sample = rows(Path(args.input), split, args.limit, args.context)
        course_vectors = model.encode([x["course"] for x in sample], batch_size=args.batch_size,
                                      normalize_embeddings=True, show_progress_bar=True)
        outcome_vectors = model.encode([x["outcome"] for x in sample], batch_size=args.batch_size,
                                       normalize_embeddings=True, show_progress_bar=True)
        scores = np.sum(course_vectors * outcome_vectors, axis=1)
        actual = np.asarray([x["actual"] for x in sample])
        stored[split] = (sample, actual, scores)
    val_sample, val_actual, val_scores = stored["validation"]
    candidates = np.linspace(float(val_scores.min()), float(val_scores.max()), 301)
    threshold = max(candidates, key=lambda value: f1_score(val_actual, val_scores >= value, zero_division=0))
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "model": args.model,
              "device": args.device, "seed": 42, "programme_level_bootstrap": True,
              "repetitions": args.repetitions, "splits": {}}
    for split, (sample, actual, scores) in stored.items():
        groups = {}
        for row, label, score in zip(sample, actual, scores):
            groups.setdefault(row["program_id"], [[], []])
            groups[row["program_id"]][0].append(int(label))
            groups[row["program_id"]][1].append(float(score))
        grouped = {k: (np.asarray(v[0]), np.asarray(v[1])) for k, v in groups.items()}
        report["splits"][split] = {
            "metrics": pooled_metrics(actual, scores, threshold),
            "programme_count": len(grouped),
            "bootstrap_ci_95": bootstrap(grouped, threshold, args.repetitions, 42),
        }
    predictions = []
    for split, (sample, actual, scores) in stored.items():
        for row, label, score in zip(sample, actual, scores):
            predictions.append({"split": split, "program_id": row["program_id"],
                                "actual": int(label), "score": float(score)})
    (output / "metrics-with-ci.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output / "predictions.jsonl").write_text("\n".join(json.dumps(x) for x in predictions) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
