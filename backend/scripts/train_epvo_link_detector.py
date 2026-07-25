"""Train a course–LO link detector with deterministic within-program negatives."""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import accuracy_score, average_precision_score, f1_score, precision_score, recall_score, roc_auc_score
from torch import nn

from train_epvo_pair_network import PairNetwork, pad, raw_text, token_ids


def pair_batches(path, split, batch_size, buckets, epoch=0):
    course_rows, outcome_rows, labels = [], [], []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            program = json.loads(line)
            if program.get("split") != split: continue
            courses = {str(row["id"]): row for row in program["courses"]}
            outcomes = {str(row["id"]): row for row in program["outcomes"]}
            positives = {(str(a), str(b)) for a, b in program["positive_edges"] if str(a) in courses and str(b) in outcomes}
            by_course = {}
            for course_id, lo_id in positives: by_course.setdefault(course_id, set()).add(lo_id)
            rng = random.Random(f"{program['program_id']}:{epoch}:42")
            pairs = []
            all_outcomes = list(outcomes)
            for course_id, positive_ids in by_course.items():
                selected_positive = sorted(positive_ids)[:3]
                negative_ids = [lo_id for lo_id in all_outcomes if lo_id not in positive_ids]
                rng.shuffle(negative_ids)
                pairs.extend((course_id, lo_id, 1.0) for lo_id in selected_positive)
                pairs.extend((course_id, lo_id, 0.0) for lo_id in negative_ids[:len(selected_positive)])
            rng.shuffle(pairs)
            for course_id, lo_id, label in pairs:
                course, outcome = courses[course_id], outcomes[lo_id]
                course_text = raw_text(course["title"]) + " " + raw_text(course["description"])
                outcome_text = raw_text(outcome["text"])
                course_rows.append(token_ids(course_text, buckets, 160)); outcome_rows.append(token_ids(outcome_text, buckets, 80)); labels.append(label)
                if len(labels) >= batch_size:
                    yield pad(course_rows), pad(outcome_rows), torch.tensor(labels, dtype=torch.float32)
                    course_rows, outcome_rows, labels = [], [], []
    if labels: yield pad(course_rows), pad(outcome_rows), torch.tensor(labels, dtype=torch.float32)


def evaluate(model, path, split, batch_size, buckets):
    actual, probability = [], []; model.eval()
    with torch.no_grad():
        for courses, outcomes, labels in pair_batches(path, split, batch_size, buckets):
            probability.extend(model(courses, outcomes).numpy().tolist()); actual.extend(labels.numpy().tolist())
    actual, probability = np.asarray(actual), np.asarray(probability); predicted = probability >= .5
    return {
        "examples": len(actual), "roc_auc": round(float(roc_auc_score(actual, probability)), 6),
        "pr_auc": round(float(average_precision_score(actual, probability)), 6),
        "accuracy": round(float(accuracy_score(actual, predicted)), 6),
        "precision": round(float(precision_score(actual, predicted)), 6),
        "recall": round(float(recall_score(actual, predicted)), 6),
        "f1": round(float(f1_score(actual, predicted)), 6),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiment-results/epvo-link-dataset/programs.jsonl")
    parser.add_argument("--output", default="experiment-results/epvo-link-detector")
    parser.add_argument("--epochs", type=int, default=1); parser.add_argument("--batch-size", type=int, default=768)
    parser.add_argument("--buckets", type=int, default=65536); args = parser.parse_args()
    torch.manual_seed(42); torch.set_num_threads(max(1, min(8, torch.get_num_threads())))
    source, output = Path(args.input), Path(args.output); output.mkdir(parents=True, exist_ok=True)
    model = PairNetwork(args.buckets); optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-5)
    loss_function = nn.BCELoss()
    for epoch in range(args.epochs):
        model.train(); total_loss = examples = 0
        for courses, outcomes, labels in pair_batches(source, "train", args.batch_size, args.buckets, epoch):
            optimizer.zero_grad(); probability = model(courses, outcomes); loss = loss_function(probability, labels)
            loss.backward(); optimizer.step(); total_loss += loss.item() * len(labels); examples += len(labels)
        print(json.dumps({"epoch": epoch + 1, "examples": examples, "loss": total_loss / examples}), flush=True)
    metrics = {
        "created_at": datetime.now(timezone.utc).isoformat(), "model_type": "hashed_pair_link_detector",
        "negative_sampling": "equal within-program unlinked outcomes; max 3 positive and 3 negative pairs per course",
        "validation": evaluate(model, source, "validation", args.batch_size, args.buckets),
        "test": evaluate(model, source, "test", args.batch_size, args.buckets),
    }
    torch.save({"state_dict": model.state_dict(), "buckets": args.buckets, "metrics": metrics}, output / "model.pt")
    (output / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__": main()
