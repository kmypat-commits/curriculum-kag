"""Train an imbalance-aware offline classifier for EPVO expert levels."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score

from train_epvo_expert_baseline import batches


CLASSES = np.asarray([0, 1, 2], dtype=np.int8)
NAMES = ["low", "medium", "high"]


def labels(scores):
    return np.where(scores < 0.25, 0, np.where(scores < 0.75, 1, 2)).astype(np.int8)


def evaluate(path, split, vectorizer, model, batch_size):
    actual, predicted, probabilities = [], [], []
    for texts, scores in batches(path, split, batch_size):
        matrix = vectorizer.transform(texts)
        actual.extend(labels(scores).tolist())
        predicted.extend(model.predict(matrix).tolist())
        probabilities.extend(np.max(model.predict_proba(matrix), axis=1).tolist())
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    matrix = confusion_matrix(actual, predicted, labels=CLASSES)
    return {
        "examples": int(len(actual)),
        "accuracy": round(float(accuracy_score(actual, predicted)), 6),
        "balanced_accuracy": round(float(balanced_accuracy_score(actual, predicted)), 6),
        "macro_f1": round(float(f1_score(actual, predicted, average="macro")), 6),
        "weighted_f1": round(float(f1_score(actual, predicted, average="weighted")), 6),
        "mean_confidence": round(float(np.mean(probabilities)), 6),
        "confusion": {
            actual_name: {predicted_name: int(matrix[i, j]) for j, predicted_name in enumerate(NAMES)}
            for i, actual_name in enumerate(NAMES)
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiment-results/epvo-expert-labels/course_lo_pairs.jsonl")
    parser.add_argument("--output", default="experiment-results/epvo-balanced-classifier")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=4096)
    args = parser.parse_args()
    source, output = Path(args.input), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    vectorizer = HashingVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), n_features=2**20,
        alternate_sign=False, norm="l2", lowercase=True,
    )
    model = SGDClassifier(
        loss="log_loss", penalty="elasticnet", alpha=2e-6, l1_ratio=0.05,
        learning_rate="optimal", average=True, random_state=42,
    )
    # Moderate weighting corrects the majority-class collapse without allowing
    # the very rare zero labels to dominate the useful medium/high boundary.
    weights = np.asarray([3.0, 1.7, 0.75], dtype=np.float32)
    distribution = Counter()
    first = True
    for epoch in range(args.epochs):
        seen = 0
        for texts, scores in batches(source, "train", args.batch_size):
            y = labels(scores); distribution.update(y.tolist())
            kwargs = {"classes": CLASSES} if first else {}
            model.partial_fit(vectorizer.transform(texts), y, sample_weight=weights[y], **kwargs)
            first = False; seen += len(y)
        print(json.dumps({"epoch": epoch + 1, "examples": seen}), flush=True)
    metrics = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_type": "balanced_hashing_char_ngrams_sgd_logistic",
        "levels": dict(enumerate(NAMES)),
        "training_distribution_across_epochs": {NAMES[k]: v for k, v in distribution.items()},
        "validation": evaluate(source, "validation", vectorizer, model, args.batch_size),
        "test": evaluate(source, "test", vectorizer, model, args.batch_size),
    }
    joblib.dump({"vectorizer": vectorizer, "model": model, "levels": NAMES}, output / "model.joblib", compress=3)
    (output / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
