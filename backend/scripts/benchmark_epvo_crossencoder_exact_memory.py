"""Benchmark CrossEncoder with exact train-only course--LO expert memory."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LOCAL_SITE_PACKAGES = ROOT / "venv" / "Lib" / "site-packages"
if LOCAL_SITE_PACKAGES.exists():
    sys.path.insert(0, str(LOCAL_SITE_PACKAGES))

from sentence_transformers import CrossEncoder, SentenceTransformer

from run_epvo_crossencoder_ranker import programme_block, ranking_metrics, query_text, selected_programmes


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source]


def train_memory(programmes: list[dict]) -> dict[tuple[str, str], float]:
    memory: dict[tuple[str, str], float] = {}
    for program in programmes:
        for edge in program.get("expert_edges") or []:
            score = edge.get("score")
            if score is None:
                continue
            key = (str(edge.get("course_id")), str(edge.get("lo_id")))
            memory[key] = max(float(score), memory.get(key, 0.0))
    return memory


def zscore(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    return (values - values.mean()) / (values.std() + 1e-6)


def collect(programmes, bi, cross, memory, bi_batch: int, cross_batch: int):
    rows = []
    for program in programmes:
        courses, outcomes, links = programme_block(program)
        if len(courses) < 2 or not links:
            continue
        course_ids = list(courses)
        lo_ids = [lo_id for lo_id in outcomes if links.get(lo_id)]
        cv = bi.encode([courses[key] for key in course_ids], batch_size=bi_batch, normalize_embeddings=True, show_progress_bar=False)
        qv = bi.encode([outcomes[key] for key in lo_ids], batch_size=bi_batch, normalize_embeddings=True, show_progress_bar=False)
        bi_scores = np.asarray(qv) @ np.asarray(cv).T
        pairs = [[outcomes[lo_id], courses[course_id]] for lo_id in lo_ids for course_id in course_ids]
        cross_scores = np.asarray(cross.predict(pairs, batch_size=cross_batch, show_progress_bar=False)).reshape(len(lo_ids), len(course_ids))
        positions = {key: i for i, key in enumerate(course_ids)}
        for row, lo_id in enumerate(lo_ids):
            exact = np.asarray([memory.get((course_id, lo_id), 0.0) for course_id in course_ids], dtype=np.float32)
            relevant = {positions[key] for key in links[lo_id] if key in positions}
            rows.append((bi_scores[row], cross_scores[row], exact, relevant))
    return rows


def blend(rows, cross_weight: float, exact_weight: float):
    result = []
    for bi, cross, exact, relevant in rows:
        scores = (1.0 - cross_weight - exact_weight) * zscore(bi) + cross_weight * zscore(cross)
        if np.any(exact):
            scores = scores + exact_weight * zscore(exact)
        result.append((scores, relevant))
    return result


def objective(metrics: dict) -> float:
    return metrics["recall_at_10"] + 0.05 * metrics["ndcg_at_10"] + 0.02 * metrics["mrr"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--bi-encoder", required=True)
    parser.add_argument("--cross-encoder", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--programmes", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=48)
    parser.add_argument("--cross-batch", type=int, default=24)
    args = parser.parse_args()
    path = Path(args.data)
    all_programmes = read(path)
    memory = train_memory([item for item in all_programmes if item.get("split") == "train"])
    bi = SentenceTransformer(args.bi_encoder, device="cuda", local_files_only=True)
    cross = CrossEncoder(args.cross_encoder, num_labels=1, max_length=192, device="cuda", local_files_only=True)
    validation = selected_programmes(path, "validation", args.programmes, "cross-exact-v1")
    test = selected_programmes(path, "test", args.programmes, "cross-exact-v1")
    validation_rows = collect(validation, bi, cross, memory, args.batch_size, args.cross_batch)
    choices = []
    grid = [round(float(value), 2) for value in np.linspace(0.0, 1.0, 21)]
    for cross_weight in grid:
        for exact_weight in grid:
            if cross_weight + exact_weight > 1.0:
                continue
            metrics = ranking_metrics(blend(validation_rows, cross_weight, exact_weight))
            choices.append({"cross_weight": cross_weight, "exact_weight": exact_weight, "objective": objective(metrics), **metrics})
    selected = max(choices, key=lambda row: (row["objective"], row["recall_at_10"], row["ndcg_at_10"]))
    test_rows = collect(test, bi, cross, memory, args.batch_size, args.cross_batch)
    baseline = ranking_metrics(blend(test_rows, 0.0, 0.0))
    cross_only = ranking_metrics(blend(test_rows, selected["cross_weight"], 0.0))
    exact_only = ranking_metrics(blend(test_rows, 0.0, selected["exact_weight"]))
    final = ranking_metrics(blend(test_rows, selected["cross_weight"], selected["exact_weight"]))
    report = {
        "method": "train-only exact stable course_id--LO_id expert memory + CrossEncoder",
        "data": str(path.resolve()), "bi_encoder": args.bi_encoder, "cross_encoder": args.cross_encoder,
        "split_policy": "programme-level frozen split", "programmes_per_split": args.programmes,
        "train_memory_edges": len(memory), "validation_selected": selected,
        "frozen_test_baseline": baseline, "frozen_test_cross_only": cross_only,
        "frozen_test_exact_only": exact_only, "frozen_test": final,
        "frozen_test_delta": {key: final[key] - baseline[key] for key in final},
        "production_model_changed": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
