"""Train a fast offline baseline that reproduces EPVO expert course–LO scores."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import SGDRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error


def text_of(row):
    title, description, lo = row["course_title"], row["course_description"], row["lo_text"]
    course_text = title.get("ru") or title.get("kz") or title.get("en") or ""
    details = description.get("ru") or description.get("kz") or description.get("en") or ""
    outcome = lo.get("ru") or lo.get("kz") or lo.get("en") or ""
    return f"ДИСЦИПЛИНА: {course_text}. ОПИСАНИЕ: {details} РЕЗУЛЬТАТ ОБУЧЕНИЯ: {outcome}"


def batches(path, split, size):
    texts, scores = [], []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            score = row.get("expert_score")
            if row.get("split") != split or score is None:
                continue
            texts.append(text_of(row)); scores.append(float(score))
            if len(texts) >= size:
                yield texts, np.asarray(scores, dtype=np.float32)
                texts, scores = [], []
    if texts:
        yield texts, np.asarray(scores, dtype=np.float32)


def level(score):
    return "low" if score < 0.25 else "medium" if score < 0.75 else "high"


def evaluate(path, split, vectorizer, model, batch_size):
    actual, predicted = [], []
    for texts, scores in batches(path, split, batch_size):
        values = np.clip(model.predict(vectorizer.transform(texts)), 0.0, 1.0)
        actual.extend(scores.tolist()); predicted.extend(values.tolist())
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    actual_levels = [level(value) for value in actual]
    predicted_levels = [level(value) for value in predicted]
    confusion = Counter(zip(actual_levels, predicted_levels))
    return {
        "examples": int(len(actual)),
        "mae": round(float(mean_absolute_error(actual, predicted)), 6),
        "rmse": round(float(math.sqrt(mean_squared_error(actual, predicted))), 6),
        "within_0.25": round(float(np.mean(np.abs(actual - predicted) <= 0.25)), 6),
        "level_accuracy": round(float(np.mean(np.asarray(actual_levels) == np.asarray(predicted_levels))), 6),
        "confusion": {f"{a}->{p}": n for (a, p), n in sorted(confusion.items())},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiment-results/epvo-expert-labels/course_lo_pairs.jsonl")
    parser.add_argument("--output", default="experiment-results/epvo-expert-baseline")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=4096)
    args = parser.parse_args()
    source, output = Path(args.input), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    vectorizer = HashingVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), n_features=2**20,
        alternate_sign=False, norm="l2", lowercase=True,
    )
    model = SGDRegressor(
        loss="huber", epsilon=0.1, penalty="l2", alpha=1e-6,
        learning_rate="optimal", average=True, random_state=42,
    )
    trained = 0
    for epoch in range(args.epochs):
        epoch_count = 0
        for texts, scores in batches(source, "train", args.batch_size):
            model.partial_fit(vectorizer.transform(texts), scores)
            epoch_count += len(scores)
        trained += epoch_count
        print(json.dumps({"epoch": epoch + 1, "examples": epoch_count}), flush=True)

    metrics = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_type": "hashing_char_ngrams_sgd_huber_regression",
        "target": "EPVO expert score in [0, 1]",
        "trained_examples_across_epochs": trained,
        "validation": evaluate(source, "validation", vectorizer, model, args.batch_size),
        "test": evaluate(source, "test", vectorizer, model, args.batch_size),
        "limitations": [
            "Baseline estimates the strength of an existing candidate link.",
            "Candidate retrieval and hard-negative link detection are evaluated separately.",
        ],
    }
    joblib.dump({"vectorizer": vectorizer, "model": model}, output / "model.joblib", compress=3)
    (output / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
