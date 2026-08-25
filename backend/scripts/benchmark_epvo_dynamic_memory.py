"""Research-only dynamic EPVO-memory reranker.

Unlike a fixed blend, this candidate adds train-only semantic-memory evidence
only when it improves a course score over the local SBERT baseline.  Weights
are selected on validation and evaluated once on a programme-disjoint test.
No production planner or model is modified.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from benchmark_epvo_scoped_memory_ranking import (
    DEFAULT_DATA,
    collect_memory,
    ranking_metrics,
    score_split,
    select_splits,
    target_scope_titles,
    target_titles,
)


def dynamic_rows(rows, global_weight: float, scoped_weight: float):
    result = []
    for base, global_prior, scoped_prior, relevant in rows:
        global_gain = np.maximum(np.asarray(global_prior) - np.asarray(base), 0.0)
        scoped_gain = np.maximum(np.asarray(scoped_prior) - np.asarray(base), 0.0)
        scores = np.asarray(base) + global_weight * global_gain + scoped_weight * scoped_gain
        result.append((scores, relevant))
    return result


def objective(metrics: dict) -> float:
    return metrics["recall_at_10"] + 0.05 * metrics["ndcg_at_10"] + 0.02 * metrics["mrr"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--programmes", type=int, default=80)
    parser.add_argument("--per-key-limit", type=int, default=32)
    parser.add_argument("--batch-size", type=int, default=48)
    parser.add_argument("--device", default="cuda", choices=("cpu", "cuda"))
    args = parser.parse_args()

    data = Path(args.data)
    selected = select_splits(
        data,
        {"validation": args.programmes, "test": args.programmes},
        "ranking-v1",
    )
    titles = target_titles(selected)
    scope_titles = target_scope_titles(selected)
    global_memory, scoped_memory, memory_stats = collect_memory(
        data, titles, scope_titles, args.per_key_limit
    )
    evidence = sorted(
        {
            text
            for memory in (global_memory, scoped_memory)
            for values in memory.values()
            for text in values
        }
    )
    model = SentenceTransformer(args.model, device=args.device, local_files_only=True)
    vectors = dict(
        zip(
            evidence,
            model.encode(
                evidence,
                batch_size=args.batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            ),
        )
    )
    validation_rows, validation_coverage = score_split(
        selected["validation"], model, global_memory, scoped_memory, vectors, args.batch_size
    )
    test_rows, test_coverage = score_split(
        selected["test"], model, global_memory, scoped_memory, vectors, args.batch_size
    )

    choices = []
    grid = np.linspace(0.0, 1.0, 11)
    for global_weight in grid:
        for scoped_weight in grid:
            metrics = ranking_metrics(dynamic_rows(validation_rows, float(global_weight), float(scoped_weight)))
            choices.append(
                {
                    "global_weight": round(float(global_weight), 2),
                    "scoped_weight": round(float(scoped_weight), 2),
                    "objective": objective(metrics),
                    **metrics,
                }
            )
    selected_weights = max(
        choices,
        key=lambda row: (row["objective"], row["recall_at_10"], row["ndcg_at_10"]),
    )
    baseline = ranking_metrics(dynamic_rows(test_rows, 0.0, 0.0))
    final = ranking_metrics(
        dynamic_rows(
            test_rows,
            selected_weights["global_weight"],
            selected_weights["scoped_weight"],
        )
    )
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "train-only semantic EPVO memory with positive-residual gating",
        "model": args.model,
        "split_policy": "programme-level frozen split",
        "programmes_per_split": args.programmes,
        "memory": memory_stats,
        "evidence_texts": len(evidence),
        "validation_coverage": validation_coverage,
        "test_coverage": test_coverage,
        "validation_selected": selected_weights,
        "frozen_test_baseline": baseline,
        "frozen_test": final,
        "frozen_test_delta": {key: final[key] - baseline[key] for key in final},
        "production_model_changed": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
