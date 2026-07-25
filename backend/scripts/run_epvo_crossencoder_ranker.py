"""Train and validate a local programme-aware CrossEncoder reranker.

The frozen test split is touched only after blend-weight selection on validation.
No production model is changed by this experiment.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import heapq
import json
import math
import random
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# The original venv launcher can become stale after moving the workspace. Reuse
# its installed packages with the bundled Python runtime without modifying them.
LOCAL_SITE_PACKAGES = Path(__file__).resolve().parents[1] / "venv" / "Lib" / "site-packages"
if LOCAL_SITE_PACKAGES.exists():
    sys.path.insert(0, str(LOCAL_SITE_PACKAGES))

import numpy as np
import torch
from sentence_transformers import CrossEncoder, InputExample, SentenceTransformer
from torch.utils.data import DataLoader


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "experiment-results" / "epvo-link-context-dataset" / "programs.jsonl"


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def localized(value: dict) -> str:
    return str(value.get("ru") or value.get("kz") or value.get("en") or "").strip()


def course_text(course: dict) -> str:
    return " | ".join(filter(None, (localized(course.get("title") or {}), localized(course.get("description") or {}))))


def query_text(program: dict, outcome: dict) -> str:
    pieces = [localized(outcome.get("text") or {})]
    context = (
        ("ЦЕЛЬ", localized(program.get("program_goal") or {})),
        ("НАПРАВЛЕНИЕ", localized(program.get("training_direction") or {})),
        ("ГРУППА", localized(program.get("program_group") or {})),
    )
    pieces.extend(f"{label}: {value}" for label, value in context if value)
    return " | ".join(pieces)


def selected_programmes(path: Path, split: str, count: int, seed_prefix: str) -> list[dict]:
    ranked: list[tuple[int, int, dict]] = []
    serial = 0
    with path.open(encoding="utf-8") as source:
        for line in source:
            program = json.loads(line)
            if program.get("split") != split:
                continue
            program_id = str(program.get("program_id"))
            rank = int(hashlib.sha256(f"{seed_prefix}:{split}:{program_id}".encode()).hexdigest(), 16)
            serial += 1
            item = (-rank, serial, program)
            if len(ranked) < count:
                heapq.heappush(ranked, item)
            elif rank < -ranked[0][0]:
                heapq.heapreplace(ranked, item)
    return [program for neg_rank, _, program in sorted(ranked, key=lambda item: -item[0])]


def programme_block(program: dict) -> tuple[dict[str, str], dict[str, str], dict[str, set[str]]]:
    courses = {
        str(item["id"]): course_text(item)
        for item in program.get("courses") or []
        if course_text(item)
    }
    outcomes = {
        str(item["id"]): query_text(program, item)
        for item in program.get("outcomes") or []
        if query_text(program, item)
    }
    links: dict[str, set[str]] = defaultdict(set)
    for course_id, lo_id in program.get("positive_edges") or []:
        course_id, lo_id = str(course_id), str(lo_id)
        if course_id in courses and lo_id in outcomes:
            links[lo_id].add(course_id)
    return courses, outcomes, links


def mine_examples(
    programmes: list[dict], model_path: str, limit: int, batch_size: int, status_path: Path
) -> tuple[list[InputExample], dict]:
    model = SentenceTransformer(model_path, device="cuda", local_files_only=True)
    rng = random.Random(42)
    samples: list[InputExample] = []
    stats = {"programmes": 0, "queries": 0, "positives": 0, "hard_negatives": 0}
    for index, program in enumerate(programmes, start=1):
        courses, outcomes, links = programme_block(program)
        if len(courses) < 2 or not links:
            continue
        course_ids = list(courses)
        lo_ids = [lo_id for lo_id in outcomes if links.get(lo_id)]
        course_vectors = model.encode(
            [courses[key] for key in course_ids], batch_size=batch_size,
            normalize_embeddings=True, show_progress_bar=False,
        )
        lo_vectors = model.encode(
            [outcomes[key] for key in lo_ids], batch_size=batch_size,
            normalize_embeddings=True, show_progress_bar=False,
        )
        scores = np.asarray(lo_vectors) @ np.asarray(course_vectors).T
        stats["programmes"] += 1
        for row, lo_id in enumerate(lo_ids):
            positives = sorted(links[lo_id], key=lambda key: -scores[row, course_ids.index(key)])[:2]
            negatives = [course_ids[pos] for pos in np.argsort(-scores[row]) if course_ids[pos] not in links[lo_id]][:2]
            if not positives or not negatives:
                continue
            stats["queries"] += 1
            for course_id in positives:
                samples.append(InputExample(texts=[outcomes[lo_id], courses[course_id]], label=1.0))
                stats["positives"] += 1
            for course_id in negatives:
                samples.append(InputExample(texts=[outcomes[lo_id], courses[course_id]], label=0.0))
                stats["hard_negatives"] += 1
        if index % 25 == 0:
            save(status_path, {"status": "mining", "programmes_seen": index, "examples": len(samples), **stats})
        if len(samples) >= limit:
            break
    del model
    gc.collect()
    torch.cuda.empty_cache()
    rng.shuffle(samples)
    samples = samples[:limit]
    return samples, {**stats, "selected_examples": len(samples), "policy": "top-2 declared positives and top-2 unlinked within-programme hard negatives"}


def ranking_metrics(scores_by_query: list[tuple[np.ndarray, set[int]]]) -> dict:
    values: dict[str, list[float]] = defaultdict(list)
    for scores, relevant in scores_by_query:
        ranking = np.argsort(-scores)
        for k in (1, 3, 5, 10):
            values[f"recall_at_{k}"].append(sum(int(pos) in relevant for pos in ranking[:k]) / len(relevant))
        first = next((position + 1 for position, item in enumerate(ranking) if int(item) in relevant), None)
        values["mrr"].append(1 / first if first else 0.0)
        dcg = sum((1 if int(item) in relevant else 0) / math.log2(position + 2) for position, item in enumerate(ranking[:10]))
        ideal = sum(1 / math.log2(position + 2) for position in range(min(len(relevant), 10)))
        values["ndcg_at_10"].append(dcg / ideal if ideal else 0.0)
    return {key: float(np.mean(value)) for key, value in values.items()}


def collect_scores(
    programmes: list[dict], bi_encoder: SentenceTransformer, cross_encoder: CrossEncoder,
    bi_batch: int, cross_batch: int, status_path: Path, split: str,
) -> list[tuple[np.ndarray, np.ndarray, set[int]]]:
    result: list[tuple[np.ndarray, np.ndarray, set[int]]] = []
    for index, program in enumerate(programmes, start=1):
        courses, outcomes, links = programme_block(program)
        if len(courses) < 2 or not links:
            continue
        course_ids = list(courses)
        lo_ids = [lo_id for lo_id in outcomes if links.get(lo_id)]
        course_vectors = bi_encoder.encode([courses[key] for key in course_ids], batch_size=bi_batch, normalize_embeddings=True, show_progress_bar=False)
        lo_vectors = bi_encoder.encode([outcomes[key] for key in lo_ids], batch_size=bi_batch, normalize_embeddings=True, show_progress_bar=False)
        bi_scores = np.asarray(lo_vectors) @ np.asarray(course_vectors).T
        pairs = [[outcomes[lo_id], courses[course_id]] for lo_id in lo_ids for course_id in course_ids]
        cross_scores = np.asarray(cross_encoder.predict(pairs, batch_size=cross_batch, show_progress_bar=False)).reshape(len(lo_ids), len(course_ids))
        course_positions = {key: pos for pos, key in enumerate(course_ids)}
        for row, lo_id in enumerate(lo_ids):
            relevant = {course_positions[key] for key in links[lo_id] if key in course_positions}
            result.append((bi_scores[row], cross_scores[row], relevant))
        if index % 10 == 0:
            save(status_path, {"status": f"benchmark_{split}", "programmes_done": index, "queries": len(result)})
    return result


def blended(rows: list[tuple[np.ndarray, np.ndarray, set[int]]], weight: float):
    return [((1.0 - weight) * bi + weight * cross, relevant) for bi, cross, relevant in rows]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--bi-encoder", default=str(ROOT / "models" / "epvo-sbert-ranking-loss-pilot"))
    parser.add_argument("--cross-base", default=str(ROOT / "models" / "epvo-sbert-finetuned-40k"))
    parser.add_argument("--name", default="epvo-crossencoder-program-hardneg-pilot")
    parser.add_argument("--train-programmes", type=int, default=240)
    parser.add_argument("--examples", type=int, default=6000)
    parser.add_argument("--validation-programmes", type=int, default=120)
    parser.add_argument("--test-programmes", type=int, default=120)
    parser.add_argument("--train-batch", type=int, default=4)
    parser.add_argument("--cross-batch", type=int, default=24)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    args = parser.parse_args()

    experiment = ROOT / "experiment-results" / args.name
    model_output = ROOT / "models" / args.name
    status_path = experiment / "run-status.json"
    status = {"status": "starting", "started_at": datetime.now(timezone.utc).isoformat(), "production_model_changed": False, **vars(args)}
    save(status_path, status)
    try:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required")
        train_programmes = selected_programmes(Path(args.data), "train", args.train_programmes, "crossencoder-v1")
        examples, mining = mine_examples(train_programmes, args.bi_encoder, args.examples, 48, status_path)
        experiment.mkdir(parents=True, exist_ok=True)
        with (experiment / "mined-pairs.jsonl").open("w", encoding="utf-8") as target:
            for item in examples:
                target.write(json.dumps({"query": item.texts[0], "course": item.texts[1], "label": item.label}, ensure_ascii=False) + "\n")
        save(status_path, {**status, "status": "training", "mining": mining, "cuda": torch.cuda.get_device_name(0)})

        cross_encoder = CrossEncoder(args.cross_base, num_labels=1, max_length=192, device="cuda", local_files_only=True)
        cross_encoder.model.gradient_checkpointing_enable()
        base = cross_encoder.model.base_model
        embeddings = getattr(base, "embeddings", None)
        if embeddings is not None:
            for parameter in embeddings.parameters():
                parameter.requires_grad = False
        layers = list(getattr(getattr(base, "encoder", None), "layer", []))
        for layer in layers[:6]:
            for parameter in layer.parameters():
                parameter.requires_grad = False
        loader = DataLoader(examples, shuffle=True, batch_size=args.train_batch)
        cross_encoder.fit(
            train_dataloader=loader, epochs=1, warmup_steps=max(10, len(loader) // 10),
            optimizer_params={"lr": args.learning_rate}, use_amp=True,
            output_path=str(model_output), save_best_model=False, show_progress_bar=True,
        )
        save(status_path, {**status, "status": "benchmark_validation", "mining": mining})

        validation = selected_programmes(Path(args.data), "validation", args.validation_programmes, "ranking-v1")
        test = selected_programmes(Path(args.data), "test", args.test_programmes, "ranking-v1")
        bi_encoder = SentenceTransformer(args.bi_encoder, device="cuda", local_files_only=True)
        validation_rows = collect_scores(validation, bi_encoder, cross_encoder, 48, args.cross_batch, status_path, "validation")
        weights = [round(value, 2) for value in np.linspace(0, 1, 21)]
        validation_results = []
        for weight in weights:
            metrics = ranking_metrics(blended(validation_rows, weight))
            objective = metrics["recall_at_10"] + 0.05 * metrics["ndcg_at_10"] + 0.02 * metrics["mrr"]
            validation_results.append({"weight": weight, "objective": objective, **metrics})
        selected = max(validation_results, key=lambda row: (row["objective"], row["recall_at_10"], row["ndcg_at_10"]))
        save(status_path, {**status, "status": "benchmark_test", "selected_weight": selected["weight"], "mining": mining})
        test_rows = collect_scores(test, bi_encoder, cross_encoder, 48, args.cross_batch, status_path, "test")
        test_metrics = ranking_metrics(blended(test_rows, selected["weight"]))
        baseline_metrics = ranking_metrics(blended(test_rows, 0.0))
        report = {
            "created_at": datetime.now(timezone.utc).isoformat(), "name": args.name,
            "data": str(Path(args.data).resolve()), "bi_encoder": args.bi_encoder,
            "cross_encoder": str(model_output), "split_policy": "programme-level frozen split",
            "mining": mining, "validation_results": validation_results,
            "selected_weight": selected["weight"], "validation_selected": selected,
            "frozen_test_baseline": baseline_metrics, "frozen_test": test_metrics,
            "frozen_test_delta": {key: test_metrics[key] - baseline_metrics[key] for key in test_metrics},
            "production_model_changed": False,
        }
        save(experiment / "metrics.json", report)
        save(status_path, {**status, "status": "complete", "completed_at": datetime.now(timezone.utc).isoformat(), "selected_weight": selected["weight"], "frozen_test": test_metrics, "production_model_changed": False})
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as error:
        save(status_path, {**status, "status": "failed", "failed_at": datetime.now(timezone.utc).isoformat(), "error": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc(limit=12), "production_model_changed": False})
        raise


if __name__ == "__main__":
    main()
