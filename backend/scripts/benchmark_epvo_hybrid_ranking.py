"""Frozen ranking experiment: SBERT plus a transparent lexical-overlap feature.

This script is deliberately evaluation-only.  It never changes the production
model or planner.  The lexical signal is computed from the selected language
texts and its weight is chosen on validation before a frozen test comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer


TOKEN_RE = re.compile(r"[\w]{3,}", re.UNICODE)


def localized(value: dict) -> str:
    return str(value.get("ru") or value.get("kz") or value.get("en") or "").strip()


def tokens(value: str) -> set[str]:
    return set(TOKEN_RE.findall(value.casefold()))


def lexical_score(course: str, outcome: str) -> float:
    left, right = tokens(course), tokens(outcome)
    if not left or not right:
        return 0.0
    # Cosine-like overlap is bounded and language-agnostic; it does not use
    # labels or any held-out programme metadata.
    return len(left & right) / math.sqrt(len(left) * len(right))


def char_score(course: str, outcome: str) -> float:
    def grams(value: str) -> set[str]:
        normalized = re.sub(r"\s+", " ", value.casefold()).strip()
        return {normalized[index:index + 3] for index in range(max(0, len(normalized) - 2))}
    left, right = grams(course), grams(outcome)
    if not left or not right:
        return 0.0
    return len(left & right) / math.sqrt(len(left) * len(right))


def select(path: Path, split: str, limit: int, seed: str) -> list[dict]:
    rows: list[tuple[int, int, dict]] = []
    serial = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            programme = json.loads(line)
            if programme.get("split") != split:
                continue
            serial += 1
            rank = int(hashlib.sha256(f"{seed}:{split}:{programme.get('program_id')}".encode()).hexdigest(), 16)
            value = (-rank, serial, programme)
            if len(rows) < limit:
                heapq.heappush(rows, value)
            elif rank < -rows[0][0]:
                heapq.heapreplace(rows, value)
    return [item[2] for item in sorted(rows, key=lambda item: -item[0])]


def score(
    programmes: list[dict],
    model: SentenceTransformer,
    batch_size: int,
    mode: str,
    use_programme_context: bool = False,
) -> list[tuple[np.ndarray, np.ndarray, set[int]]]:
    result = []
    for programme in programmes:
        courses = {str(x["id"]): x for x in programme.get("courses") or []}
        outcomes = {str(x["id"]): x for x in programme.get("outcomes") or []}
        links: dict[str, set[str]] = defaultdict(set)
        for course_id, lo_id in programme.get("positive_edges") or []:
            if str(course_id) in courses and str(lo_id) in outcomes:
                links[str(lo_id)].add(str(course_id))
        course_ids = [key for key, item in courses.items() if localized(item.get("title") or {})]
        lo_ids = [key for key in outcomes if links.get(key) and localized(outcomes[key].get("text") or {})]
        if len(course_ids) < 2 or not lo_ids:
            continue
        course_texts = [" | ".join(filter(None, (localized(courses[key].get("title") or {}), localized(courses[key].get("description") or {})))) for key in course_ids]
        context = " | ".join(
            localized(programme.get(field) or {})
            for field in ("program_goal", "training_direction", "program_group")
            if localized(programme.get(field) or {})
        )
        lo_texts = [
            f"{localized(outcomes[key].get('text') or {})} | {context}"
            if use_programme_context and context
            else localized(outcomes[key].get("text") or {})
            for key in lo_ids
        ]
        cvec = model.encode(course_texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
        lvec = model.encode(lo_texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
        base = np.asarray(lvec) @ np.asarray(cvec).T
        lexical = np.asarray([[
            (lexical_score(course_texts[col], lo_text) if mode == "word" else
             char_score(course_texts[col], lo_text) if mode == "char" else
             0.7 * lexical_score(course_texts[col], lo_text) + 0.3 * char_score(course_texts[col], lo_text))
            for col in range(len(course_ids))
        ] for lo_text in lo_texts])
        positions = {key: pos for pos, key in enumerate(course_ids)}
        for row, lo_id in enumerate(lo_ids):
            relevant = {positions[key] for key in links[lo_id] if key in positions}
            result.append((base[row], lexical[row], relevant))
    return result


def metrics(rows: list[tuple[np.ndarray, np.ndarray, set[int]]], weight: float) -> dict:
    values: dict[str, list[float]] = defaultdict(list)
    for base, lexical, relevant in rows:
        scores = (1.0 - weight) * base + weight * lexical
        ranking = np.argsort(-scores)
        for k in (1, 3, 5, 10):
            values[f"recall_at_{k}"].append(sum(int(pos) in relevant for pos in ranking[:k]) / len(relevant))
        first = next((pos + 1 for pos, item in enumerate(ranking) if int(item) in relevant), None)
        values["mrr"].append(1 / first if first else 0.0)
        dcg = sum((1 if int(item) in relevant else 0) / math.log2(pos + 2) for pos, item in enumerate(ranking[:10]))
        ideal = sum(1 / math.log2(pos + 2) for pos in range(min(len(relevant), 10)))
        values["ndcg_at_10"].append(dcg / ideal if ideal else 0.0)
    return {key: float(np.mean(value)) for key, value in values.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="experiment-results/epvo-link-context-dataset/programs.jsonl")
    parser.add_argument("--model", default="models/epvo-sbert-ranking-loss-pilot")
    parser.add_argument("--output", default=".runtime/epvo-ranking-hybrid-lexical.json")
    parser.add_argument("--programmes", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--device", default="cuda", choices=("cpu", "cuda"))
    parser.add_argument("--lexical-mode", default="word", choices=("word", "char", "mixed"))
    parser.add_argument(
        "--programme-context",
        action="store_true",
        help="Append programme goal/direction/group to each LO query (evaluation-only).",
    )
    args = parser.parse_args()
    # Keep repeated CUDA evaluations comparable.  The experiment is
    # evaluation-only, so deterministic kernels are preferable to throughput.
    import random
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(42)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    data = Path(args.data)
    model = SentenceTransformer(args.model, device=args.device, local_files_only=True)
    model.eval()
    validation = score(
        select(data, "validation", args.programmes, "ranking-v1"),
        model,
        args.batch_size,
        args.lexical_mode,
        args.programme_context,
    )
    test = score(
        select(data, "test", args.programmes, "ranking-v1"),
        model,
        args.batch_size,
        args.lexical_mode,
        args.programme_context,
    )
    results = [{"weight": round(weight, 2), **metrics(validation, weight)} for weight in np.linspace(0, 1, 21)]
    selected = max(results, key=lambda row: (row["recall_at_10"] + 0.05 * row["ndcg_at_10"] + 0.02 * row["mrr"], row["recall_at_10"]))["weight"]
    baseline = metrics(test, 0.0)
    hybrid = metrics(test, selected)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "SBERT ranking-loss pilot plus transparent token-overlap; validation-selected weight",
        "lexical_mode": args.lexical_mode,
        "programme_context": args.programme_context,
        "split_policy": "programme-level frozen split",
        "seed": 42,
        "selected_weight": selected,
        "validation": results,
        "frozen_test_baseline": baseline,
        "frozen_test_hybrid": hybrid,
        "frozen_test_delta": {key: hybrid[key] - baseline[key] for key in hybrid},
        "production_model_changed": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
