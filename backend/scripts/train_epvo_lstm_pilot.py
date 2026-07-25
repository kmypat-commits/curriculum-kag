"""LSTM pilot for EPVO course-to-learning-outcome link prediction.

The script is intentionally conservative:
- programme-level frozen split is used;
- target course-LO edge is predicted from the course sequence and LO text;
- no test programmes are used for training;
- default limits are small enough for a controlled local run.
"""

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
    rows: list[dict] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def normalize(matrix: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norm, 1e-9)


def course_text(course: dict) -> str:
    return ". ".join(filter(None, [
        course.get("title_ru") or course.get("title") or course.get("code"),
        course.get("description_ru"),
        course.get("title_en"),
    ]))


def lo_text(lo: dict) -> str:
    return lo.get("text") or lo.get("code") or ""


def build_examples(programs: list[dict], encoder: SentenceTransformer, batch_size: int, seed: int, max_seq_len: int):
    texts: list[str] = []
    slices: list[tuple[int, int, int]] = []
    for program in programs:
        courses = sorted(program.get("courses") or [], key=lambda c: (c.get("semester") or 99, c.get("code") or ""))
        outcomes = program.get("program_learning_outcomes") or []
        start = len(texts)
        texts.extend(course_text(course) for course in courses)
        middle = len(texts)
        texts.extend(lo_text(lo) for lo in outcomes)
        slices.append((start, middle, len(texts)))
        program["_ordered_courses"] = courses
    if not texts:
        return np.empty((0, 0, 0), np.float32), np.empty((0, 0), np.float32), np.empty(0, np.float32), np.empty(0, np.float32)

    vectors = normalize(encoder.encode(texts, batch_size=batch_size, show_progress_bar=True, convert_to_numpy=True))
    sequences, lo_vectors, labels, baseline = [], [], [], []
    for program, (start, middle, end) in zip(programs, slices):
        courses = program["_ordered_courses"]
        outcomes = program.get("program_learning_outcomes") or []
        if len(courses) < 2 or len(outcomes) < 2:
            continue
        cvec, lvec = vectors[start:middle], vectors[middle:end]
        lo_index = {str(lo.get("code")): index for index, lo in enumerate(outcomes)}
        positives = {
            (ci, lo_index[str(code)])
            for ci, course in enumerate(courses)
            for code in (course.get("learning_outcomes") or [])
            if str(code) in lo_index
        }
        if not positives:
            continue
        rng = random.Random(f"{seed}:{program.get('program_id')}")
        pairs = [(pair, 1) for pair in sorted(positives)]
        for ci, _ in sorted(positives):
            negatives = [li for li in range(len(outcomes)) if (ci, li) not in positives]
            if negatives:
                pairs.append(((ci, rng.choice(negatives)), 0))
        rng.shuffle(pairs)
        for (ci, li), label in pairs:
            prefix = cvec[max(0, ci + 1 - max_seq_len): ci + 1]
            sequences.append(prefix)
            lo_vectors.append(lvec[li])
            labels.append(label)
            baseline.append(float(np.dot(cvec[ci], lvec[li])))

    if not sequences:
        return np.empty((0, 0, 0), np.float32), np.empty((0, 0), np.float32), np.empty(0, np.float32), np.empty(0, np.float32)
    max_len = max(seq.shape[0] for seq in sequences)
    dim = sequences[0].shape[1]
    padded = np.zeros((len(sequences), max_len, dim), dtype=np.float32)
    for index, seq in enumerate(sequences):
        padded[index, : seq.shape[0], :] = seq
    return padded, np.asarray(lo_vectors, np.float32), np.asarray(labels, np.float32), np.asarray(baseline, np.float32)


class LstmLinkPredictor(torch.nn.Module):
    def __init__(self, embedding_dim: int, hidden_dim: int = 128):
        super().__init__()
        self.lstm = torch.nn.LSTM(embedding_dim, hidden_dim, batch_first=True)
        self.head = torch.nn.Sequential(
            torch.nn.Linear(hidden_dim + embedding_dim + 1, 128),
            torch.nn.ReLU(),
            torch.nn.Dropout(0.15),
            torch.nn.Linear(128, 1),
        )

    def forward(self, sequence: torch.Tensor, lo_vector: torch.Tensor) -> torch.Tensor:
        _, (hidden, _) = self.lstm(sequence)
        course_state = hidden[-1]
        cosine = torch.nn.functional.cosine_similarity(course_state[:, : lo_vector.shape[1]], lo_vector, dim=1).unsqueeze(1) if course_state.shape[1] >= lo_vector.shape[1] else torch.zeros((sequence.shape[0], 1), device=sequence.device)
        return self.head(torch.cat([course_state, lo_vector, cosine], dim=1)).squeeze(1)


def best_threshold(actual: np.ndarray, predicted: np.ndarray) -> float:
    candidates = np.linspace(float(predicted.min()), float(predicted.max()), 301)
    return float(max(candidates, key=lambda value: f1_score(actual, predicted >= value)))


def scores(actual: np.ndarray, predicted: np.ndarray, threshold: float) -> dict:
    binary = predicted >= threshold
    return {
        "examples": int(len(actual)),
        "roc_auc": float(roc_auc_score(actual, predicted)),
        "pr_auc": float(average_precision_score(actual, predicted)),
        "f1": float(f1_score(actual, binary)),
        "threshold": float(threshold),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--splits", default="backend/experiment-results/epvo-ml-pilot/splits-v2")
    parser.add_argument("--model", default="backend/models/epvo-sbert-finetuned-40k")
    parser.add_argument("--output", default="backend/experiment-results/lstm-gnn-controlled-run/lstm-smoke")
    parser.add_argument("--program-limit", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=48)
    parser.add_argument("--train-batch-size", type=int, default=32)
    parser.add_argument("--max-seq-len", type=int, default=16)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    encoder = SentenceTransformer(args.model, local_files_only=True, device=device)

    datasets = {}
    for split in ("train", "validation", "test"):
        programs = read_programs(Path(args.splits) / f"{split}.jsonl", args.program_limit)
        datasets[split] = build_examples(programs, encoder, args.batch_size, args.seed, args.max_seq_len)

    x_train, lo_train, y_train, _ = datasets["train"]
    if len(y_train) < 10:
        raise SystemExit("Not enough training examples for LSTM pilot")
    network = LstmLinkPredictor(x_train.shape[2]).to(device)
    optimizer = torch.optim.AdamW(network.parameters(), lr=1e-3, weight_decay=1e-4)
    for _ in range(args.epochs):
        network.train()
        order = np.random.permutation(len(y_train))
        for start in range(0, len(order), args.train_batch_size):
            batch = order[start:start + args.train_batch_size]
            tx = torch.from_numpy(x_train[batch]).to(device)
            tl = torch.from_numpy(lo_train[batch]).to(device)
            ty = torch.from_numpy(y_train[batch]).to(device)
            optimizer.zero_grad()
            loss = torch.nn.functional.binary_cross_entropy_with_logits(network(tx, tl), ty)
            loss.backward()
            optimizer.step()

    predictions = {}
    network.eval()
    with torch.no_grad():
        for split, (x, lo, _, _) in datasets.items():
            parts = []
            for start in range(0, len(x), args.train_batch_size):
                xb = torch.from_numpy(x[start:start + args.train_batch_size]).to(device)
                lb = torch.from_numpy(lo[start:start + args.train_batch_size]).to(device)
                parts.append(torch.sigmoid(network(xb, lb)).cpu().numpy())
            predictions[split] = np.concatenate(parts) if parts else np.asarray([], dtype=np.float32)
    lstm_threshold = best_threshold(datasets["validation"][2], predictions["validation"])
    base_threshold = best_threshold(datasets["validation"][2], datasets["validation"][3])
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "device": device,
        "encoder": args.model,
        "program_limit_per_split": args.program_limit,
        "train_batch_size": args.train_batch_size,
        "max_seq_len": args.max_seq_len,
        "method": "semester-ordered course-prefix LSTM + LO vector classifier",
        "leakage_control": "programme-level split; test programmes are never used for training",
        "baseline": {s: scores(datasets[s][2], datasets[s][3], base_threshold) for s in ("validation", "test")},
        "lstm": {s: scores(datasets[s][2], predictions[s], lstm_threshold) for s in ("validation", "test")},
    }
    torch.save({"state_dict": network.state_dict(), "seed": args.seed, "embedding_dim": int(x_train.shape[2])}, output / "model.pt")
    (output / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
