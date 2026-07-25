"""Inductive one-hop GNN pilot for EPVO course-LO link prediction."""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score


def read_programs(path: Path, limit: int) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def normalize(matrix: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norm, 1e-9)


def build_examples(programs: list[dict], model: SentenceTransformer, batch_size: int, seed: int):
    texts, slices = [], []
    for program in programs:
        course_texts = [". ".join(filter(None, [c.get("title_ru") or c["title"], c.get("description_ru"), c.get("title_en")])) for c in program["courses"]]
        lo_texts = [lo.get("text") or lo["code"] for lo in program["program_learning_outcomes"]]
        start = len(texts); texts.extend(course_texts); middle = len(texts); texts.extend(lo_texts)
        slices.append((start, middle, len(texts)))
    vectors = normalize(model.encode(texts, batch_size=batch_size, show_progress_bar=True, convert_to_numpy=True))

    feature_rows, labels, baseline = [], [], []
    for program, (start, middle, end) in zip(programs, slices):
        courses, outcomes = program["courses"], program["program_learning_outcomes"]
        cvec, lvec = vectors[start:middle], vectors[middle:end]
        lo_index = {str(lo["code"]): index for index, lo in enumerate(outcomes)}
        positives = {(ci, lo_index[str(code)]) for ci, course in enumerate(courses) for code in course["learning_outcomes"] if str(code) in lo_index}
        if len(positives) < 2 or len(outcomes) < 2:
            continue
        rng = random.Random(f"{seed}:{program['program_id']}")
        ordered = sorted(positives); rng.shuffle(ordered)
        holdout_count = max(1, int(round(len(ordered) * 0.2)))
        targets, context = set(ordered[:holdout_count]), set(ordered[holdout_count:])
        if not context:
            context.add(targets.pop())

        csum = np.zeros_like(cvec); lsum = np.zeros_like(lvec)
        cdeg = np.zeros(len(courses), dtype=np.float32); ldeg = np.zeros(len(outcomes), dtype=np.float32)
        for ci, li in context:
            csum[ci] += lvec[li]; cdeg[ci] += 1
            lsum[li] += cvec[ci]; ldeg[li] += 1
        cagg = normalize(csum / np.maximum(cdeg[:, None], 1))
        lagg = normalize(lsum / np.maximum(ldeg[:, None], 1))

        pairs = [(pair, 1) for pair in targets]
        for ci, li in targets:
            candidates = [index for index in range(len(outcomes)) if (ci, index) not in positives]
            if candidates:
                pairs.append(((ci, rng.choice(candidates)), 0))
        for (ci, li), label in pairs:
            base = float(np.dot(cvec[ci], lvec[li]))
            features = [
                base,
                float(np.dot(cagg[ci], lvec[li])) if cdeg[ci] else 0.0,
                float(np.dot(cvec[ci], lagg[li])) if ldeg[li] else 0.0,
                float(np.dot(cagg[ci], lagg[li])) if cdeg[ci] and ldeg[li] else 0.0,
                float(np.log1p(cdeg[ci])), float(np.log1p(ldeg[li])),
            ]
            feature_rows.append(features); labels.append(label); baseline.append(base)
    return np.asarray(feature_rows, np.float32), np.asarray(labels, np.float32), np.asarray(baseline, np.float32)


def scores(actual: np.ndarray, predicted: np.ndarray, threshold: float) -> dict:
    binary = predicted >= threshold
    return {
        "examples": int(len(actual)), "roc_auc": float(roc_auc_score(actual, predicted)),
        "pr_auc": float(average_precision_score(actual, predicted)),
        "f1": float(f1_score(actual, binary)), "threshold": float(threshold),
    }


def best_threshold(actual: np.ndarray, predicted: np.ndarray) -> float:
    candidates = np.linspace(float(predicted.min()), float(predicted.max()), 301)
    return float(max(candidates, key=lambda value: f1_score(actual, predicted >= value)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--splits", default="experiment-results/epvo-ml-pilot/splits-v2")
    parser.add_argument("--model", default="models/epvo-sbert-finetuned-40k")
    parser.add_argument("--output", default="experiment-results/epvo-gnn-pilot")
    parser.add_argument("--program-limit", type=int, default=600)
    parser.add_argument("--batch-size", type=int, default=48)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    root, output = Path(args.splits), Path(args.output); output.mkdir(parents=True, exist_ok=True)
    encoder = SentenceTransformer(args.model, local_files_only=True, device=device)
    datasets = {}
    for split in ("train", "validation", "test"):
        programmes = read_programs(root / f"{split}.jsonl", args.program_limit)
        datasets[split] = build_examples(programmes, encoder, args.batch_size, args.seed)

    network = torch.nn.Sequential(torch.nn.Linear(6, 32), torch.nn.ReLU(), torch.nn.Dropout(0.1), torch.nn.Linear(32, 1)).to(device)
    optimizer = torch.optim.AdamW(network.parameters(), lr=2e-3, weight_decay=1e-4)
    x_train = torch.from_numpy(datasets["train"][0]).to(device)
    y_train = torch.from_numpy(datasets["train"][1]).to(device)
    for _ in range(args.epochs):
        network.train(); optimizer.zero_grad()
        loss = torch.nn.functional.binary_cross_entropy_with_logits(network(x_train).squeeze(1), y_train)
        loss.backward(); optimizer.step()

    predictions = {}
    network.eval()
    with torch.no_grad():
        for split, (features, actual, baseline) in datasets.items():
            predictions[split] = torch.sigmoid(network(torch.from_numpy(features).to(device)).squeeze(1)).cpu().numpy()
    gnn_threshold = best_threshold(datasets["validation"][1], predictions["validation"])
    base_threshold = best_threshold(datasets["validation"][1], datasets["validation"][2])
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(), "seed": args.seed, "device": device,
        "encoder": args.model, "program_limit_per_split": args.program_limit,
        "method": "one-hop mean-aggregation GNN with held-out target edges",
        "leakage_control": "split by programmes; target edges removed before aggregation",
        "baseline": {s: scores(datasets[s][1], datasets[s][2], base_threshold) for s in ("validation", "test")},
        "gnn": {s: scores(datasets[s][1], predictions[s], gnn_threshold) for s in ("validation", "test")},
    }
    torch.save({"state_dict": network.state_dict(), "seed": args.seed, "feature_count": 6}, output / "model.pt")
    (output / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
