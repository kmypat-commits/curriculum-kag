"""Leakage-safe CrossEncoder + EPVO expert-memory benchmark.

The script is research-only: it never writes production model/configuration.
Historical memory is built from train programmes only and keyed by stable
course id. Blend weights are selected on validation; the programme-disjoint
test split is evaluated once afterwards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LOCAL_SITE_PACKAGES = ROOT / "venv" / "Lib" / "site-packages"
if LOCAL_SITE_PACKAGES.exists():
    sys.path.insert(0, str(LOCAL_SITE_PACKAGES))

from sentence_transformers import CrossEncoder, SentenceTransformer

from run_epvo_crossencoder_ranker import (
    collect_scores,
    programme_block,
    query_text,
    ranking_metrics,
    selected_programmes,
)


def read_programmes(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source]


def build_memory(programmes: list[dict]) -> dict[str, list[str]]:
    memory: dict[str, list[str]] = defaultdict(list)
    for program in programmes:
        courses, outcomes, _ = programme_block(program)
        outcome_by_id = {
            str(item["id"]): query_text(program, item)
            for item in program.get("outcomes") or []
            if query_text(program, item)
        }
        for edge in program.get("expert_edges") or []:
            score = edge.get("score")
            if score is None or float(score) < 0.5:
                continue
            course_id = str(edge.get("course_id"))
            lo_id = str(edge.get("lo_id"))
            if course_id in courses and lo_id in outcome_by_id:
                if outcome_by_id[lo_id] not in memory[course_id]:
                    memory[course_id].append(outcome_by_id[lo_id])
    return dict(memory)


def zscore(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    return (values - values.mean()) / (values.std() + 1e-6)


def collect_memory_rows(
    programmes: list[dict], bi_encoder: SentenceTransformer,
    cross_encoder: CrossEncoder, memory: dict[str, list[str]],
    memory_vectors: dict[str, np.ndarray],
    bi_batch: int, cross_batch: int,
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, set[int]]]:
    rows: list[tuple[np.ndarray, np.ndarray, np.ndarray, set[int]]] = []
    for program in programmes:
        courses, outcomes, links = programme_block(program)
        if len(courses) < 2 or not links:
            continue
        course_ids = list(courses)
        lo_ids = [lo_id for lo_id in outcomes if links.get(lo_id)]
        cv = bi_encoder.encode(
            [courses[key] for key in course_ids], batch_size=bi_batch,
            normalize_embeddings=True, show_progress_bar=False,
        )
        qv = bi_encoder.encode(
            [outcomes[key] for key in lo_ids], batch_size=bi_batch,
            normalize_embeddings=True, show_progress_bar=False,
        )
        bi_scores = np.asarray(qv) @ np.asarray(cv).T
        pairs = [[outcomes[lo_id], courses[course_id]] for lo_id in lo_ids for course_id in course_ids]
        cross_scores = np.asarray(
            cross_encoder.predict(pairs, batch_size=cross_batch, show_progress_bar=False)
        ).reshape(len(lo_ids), len(course_ids))
        positions = {key: index for index, key in enumerate(course_ids)}
        for row, lo_id in enumerate(lo_ids):
            memory_scores = np.zeros(len(course_ids), dtype=np.float32)
            query = np.asarray(qv[row])
            for col, course_id in enumerate(course_ids):
                vectors = memory_vectors.get(course_id)
                if vectors is not None and len(vectors):
                    memory_scores[col] = float(np.max(np.asarray(vectors) @ query))
            relevant = {positions[key] for key in links[lo_id] if key in positions}
            rows.append((bi_scores[row], cross_scores[row], memory_scores, relevant))
    return rows


def blend(rows, cross_weight: float, memory_weight: float):
    result = []
    for bi, cross, memory, relevant in rows:
        base = zscore(bi)
        cross_norm = zscore(cross)
        memory_norm = zscore(memory) if np.any(memory) else np.zeros_like(base)
        scores = (1.0 - cross_weight - memory_weight) * base + cross_weight * cross_norm + memory_weight * memory_norm
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
    data = Path(args.data)
    all_programmes = read_programmes(data)
    train = [item for item in all_programmes if item.get("split") == "train"]
    memory = build_memory(train)
    memory_texts = sorted({text for values in memory.values() for text in values})
    model = SentenceTransformer(args.bi_encoder, device="cuda", local_files_only=True)
    encoded = model.encode(memory_texts, batch_size=args.batch_size, normalize_embeddings=True, show_progress_bar=False)
    lookup = dict(zip(memory_texts, encoded))
    memory_vectors = {course: np.asarray([lookup[text] for text in texts]) for course, texts in memory.items()}
    cross = CrossEncoder(args.cross_encoder, num_labels=1, max_length=192, device="cuda", local_files_only=True)
    validation = selected_programmes(data, "validation", args.programmes, "cross-memory-v2")
    test = selected_programmes(data, "test", args.programmes, "cross-memory-v2")
    validation_rows = collect_memory_rows(validation, model, cross, memory, memory_vectors, args.batch_size, args.cross_batch)
    choices = []
    for cross_weight in np.linspace(0.0, 1.0, 11):
        for memory_weight in np.linspace(0.0, 1.0 - cross_weight, 11):
            metrics = ranking_metrics(blend(validation_rows, float(cross_weight), float(memory_weight)))
            choices.append({"cross_weight": round(float(cross_weight), 2), "memory_weight": round(float(memory_weight), 2), "objective": objective(metrics), **metrics})
    selected = max(choices, key=lambda row: (row["objective"], row["recall_at_10"], row["ndcg_at_10"]))
    test_rows = collect_memory_rows(test, model, cross, memory, memory_vectors, args.batch_size, args.cross_batch)
    baseline = ranking_metrics(blend(test_rows, 0.0, 0.0))
    final = ranking_metrics(blend(test_rows, selected["cross_weight"], selected["memory_weight"]))
    report = {
        "method": "train-only CrossEncoder + stable-course-id expert memory",
        "data": str(data.resolve()), "bi_encoder": args.bi_encoder, "cross_encoder": args.cross_encoder,
        "split_policy": "programme-level frozen split", "programmes_per_split": args.programmes,
        "memory_courses": len(memory), "memory_texts": len(memory_texts),
        "validation_selected": selected, "frozen_test_baseline": baseline, "frozen_test": final,
        "frozen_test_delta": {key: final[key] - baseline[key] for key in final},
        "production_model_changed": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
