"""Train a compact pair-interaction network from scratch; no model download needed."""
from __future__ import annotations

import argparse
import json
import math
import re
import zlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from torch import nn


TOKEN = re.compile(r"\w+", re.UNICODE)


def raw_text(values):
    return values.get("ru") or values.get("kz") or values.get("en") or ""


def token_ids(text, buckets, limit):
    words = TOKEN.findall(text.casefold())[:limit]
    return [1 + zlib.crc32(word.encode("utf-8")) % (buckets - 1) for word in words] or [0]


def row_texts(row):
    course = raw_text(row["course_title"]) + " " + raw_text(row["course_description"])
    outcome = raw_text(row["lo_text"])
    return course, outcome


def batches(path, split, batch_size, buckets):
    courses, outcomes, scores = [], [], []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line); score = row.get("expert_score")
            if row.get("split") != split or score is None: continue
            course, outcome = row_texts(row)
            courses.append(token_ids(course, buckets, 160))
            outcomes.append(token_ids(outcome, buckets, 80))
            scores.append(float(score))
            if len(scores) >= batch_size:
                yield pad(courses), pad(outcomes), torch.tensor(scores, dtype=torch.float32)
                courses, outcomes, scores = [], [], []
    if scores:
        yield pad(courses), pad(outcomes), torch.tensor(scores, dtype=torch.float32)


def pad(rows):
    width = max(map(len, rows)); result = torch.zeros((len(rows), width), dtype=torch.long)
    for index, row in enumerate(rows): result[index, :len(row)] = torch.tensor(row)
    return result


class PairNetwork(nn.Module):
    def __init__(self, buckets=65536, dimension=64):
        super().__init__()
        self.embedding = nn.Embedding(buckets, dimension, padding_idx=0)
        self.network = nn.Sequential(
            nn.Linear(dimension * 4, 128), nn.ReLU(), nn.Dropout(0.15),
            nn.Linear(128, 32), nn.ReLU(), nn.Linear(32, 1), nn.Sigmoid(),
        )

    def encode(self, ids):
        mask = ids.ne(0).unsqueeze(-1)
        return (self.embedding(ids) * mask).sum(1) / mask.sum(1).clamp_min(1)

    def forward(self, course_ids, outcome_ids):
        course, outcome = self.encode(course_ids), self.encode(outcome_ids)
        features = torch.cat((course, outcome, torch.abs(course - outcome), course * outcome), dim=1)
        return self.network(features).squeeze(1)


def evaluate(model, path, split, batch_size, buckets):
    actual, predicted = [], []; model.eval()
    with torch.no_grad():
        for courses, outcomes, scores in batches(path, split, batch_size, buckets):
            predicted.extend(model(courses, outcomes).numpy().tolist()); actual.extend(scores.numpy().tolist())
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    levels_a = np.where(actual < .25, 0, np.where(actual < .75, 1, 2))
    levels_p = np.where(predicted < .25, 0, np.where(predicted < .75, 1, 2))
    return {
        "examples": len(actual), "mae": round(float(np.mean(np.abs(actual - predicted))), 6),
        "rmse": round(float(math.sqrt(np.mean((actual - predicted) ** 2))), 6),
        "within_0.25": round(float(np.mean(np.abs(actual - predicted) <= .25)), 6),
        "level_accuracy": round(float(np.mean(levels_a == levels_p)), 6),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiment-results/epvo-expert-labels/course_lo_pairs.jsonl")
    parser.add_argument("--output", default="experiment-results/epvo-pair-network")
    parser.add_argument("--epochs", type=int, default=2); parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--buckets", type=int, default=65536); args = parser.parse_args()
    torch.manual_seed(42); torch.set_num_threads(max(1, min(8, torch.get_num_threads())))
    source, output = Path(args.input), Path(args.output); output.mkdir(parents=True, exist_ok=True)
    model = PairNetwork(args.buckets); optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-5)
    loss_function = nn.SmoothL1Loss(beta=.2)
    for epoch in range(args.epochs):
        model.train(); loss_sum = examples = 0
        for courses, outcomes, scores in batches(source, "train", args.batch_size, args.buckets):
            optimizer.zero_grad(); prediction = model(courses, outcomes)
            loss = loss_function(prediction, scores); loss.backward(); optimizer.step()
            loss_sum += loss.item() * len(scores); examples += len(scores)
        print(json.dumps({"epoch": epoch + 1, "examples": examples, "loss": loss_sum / examples}), flush=True)
    metrics = {
        "created_at": datetime.now(timezone.utc).isoformat(), "model_type": "hashed_pair_interaction_network",
        "runtime": "local_cpu", "downloads": False,
        "validation": evaluate(model, source, "validation", args.batch_size, args.buckets),
        "test": evaluate(model, source, "test", args.batch_size, args.buckets),
    }
    torch.save({"state_dict": model.state_dict(), "buckets": args.buckets, "metrics": metrics}, output / "model.pt")
    (output / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__": main()
