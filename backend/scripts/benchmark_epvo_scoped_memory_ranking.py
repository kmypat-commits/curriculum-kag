"""Evaluate global + EPVO-group scoped expert memory on frozen ranking splits."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

LOCAL_SITE = Path(__file__).resolve().parents[1] / "venv" / "Lib" / "site-packages"
if LOCAL_SITE.exists():
    sys.path.insert(0, str(LOCAL_SITE))

import numpy as np

from benchmark_epvo_expert_memory_ranking import (
    ROOT,
    course_text,
    course_title,
    localized,
    normalize,
    select_splits,
    target_titles,
)
from sentence_transformers import SentenceTransformer


DEFAULT_DATA = ROOT / "experiment-results" / "epvo-link-context-dataset" / "programs.jsonl"


def scope_key(program: dict) -> str:
    group = normalize(localized(program.get("program_group") or {}))
    direction = normalize(localized(program.get("training_direction") or {}))
    return group or direction


def bounded_add(bucket: dict[str, str], text: str, limit: int) -> None:
    key = hashlib.sha1(normalize(text).encode("utf-8")).hexdigest()
    bucket[key] = text
    if len(bucket) > limit:
        del bucket[max(bucket)]


def target_scope_titles(selected: dict[str, list[dict]]) -> set[tuple[str, str]]:
    return {
        (scope_key(program), normalize(course_title(course)))
        for programmes in selected.values()
        for program in programmes
        for course in program.get("courses") or []
        if scope_key(program) and course_title(course)
    }


def collect_memory(path: Path, titles: set[str], scope_titles: set[tuple[str, str]], limit: int):
    global_raw: dict[str, dict[str, str]] = defaultdict(dict)
    scoped_raw: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    scanned = matching = scoped_matching = 0
    with path.open(encoding="utf-8") as source:
        for line in source:
            program = json.loads(line)
            if program.get("split") != "train":
                continue
            scanned += 1
            scope = scope_key(program)
            courses = {
                str(item["id"]): normalize(course_title(item))
                for item in program.get("courses") or []
                if normalize(course_title(item)) in titles
            }
            if not courses:
                continue
            outcomes = {
                str(item["id"]): localized(item.get("text") or {})
                for item in program.get("outcomes") or []
                if localized(item.get("text") or {})
            }
            for course_id, lo_id in program.get("positive_edges") or []:
                title, text = courses.get(str(course_id)), outcomes.get(str(lo_id))
                if not title or not text:
                    continue
                bounded_add(global_raw[title], text, limit)
                matching += 1
                if (scope, title) in scope_titles:
                    bounded_add(scoped_raw[(scope, title)], text, limit)
                    scoped_matching += 1
    global_memory = {key: list(value.values()) for key, value in global_raw.items()}
    scoped_memory = {key: list(value.values()) for key, value in scoped_raw.items()}
    stats = {
        "train_programmes_scanned": scanned,
        "global_titles": len(global_memory),
        "scoped_title_keys": len(scoped_memory),
        "global_matching_edges": matching,
        "scoped_matching_edges": scoped_matching,
        "global_unique_evidence": sum(map(len, global_memory.values())),
        "scoped_unique_evidence": sum(map(len, scoped_memory.values())),
        "per_key_limit": limit,
    }
    return global_memory, scoped_memory, stats


def aggregate(query_vectors: np.ndarray, evidence: list[str], vectors: dict[str, np.ndarray]) -> np.ndarray:
    matrix = np.asarray([vectors[text] for text in evidence])
    similarity = query_vectors @ matrix.T
    top = np.sort(similarity, axis=1)[:, -min(3, similarity.shape[1]):]
    return 0.75 * similarity.max(axis=1) + 0.25 * top.mean(axis=1)


def score_split(programmes, model, global_memory, scoped_memory, vectors, batch_size):
    rows = []
    coverage = defaultdict(int)
    for program in programmes:
        courses = {str(item["id"]): item for item in program.get("courses") or []}
        outcomes = {str(item["id"]): item for item in program.get("outcomes") or []}
        links: dict[str, set[str]] = defaultdict(set)
        for course_id, lo_id in program.get("positive_edges") or []:
            if str(course_id) in courses and str(lo_id) in outcomes:
                links[str(lo_id)].add(str(course_id))
        course_ids = [key for key, item in courses.items() if course_text(item)]
        lo_ids = [key for key, item in outcomes.items() if links.get(key) and localized(item.get("text") or {})]
        if len(course_ids) < 2 or not lo_ids:
            continue
        course_vectors = model.encode([course_text(courses[key]) for key in course_ids], batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
        query_vectors = model.encode([localized(outcomes[key].get("text") or {}) for key in lo_ids], batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
        base = np.asarray(query_vectors) @ np.asarray(course_vectors).T
        global_prior, scoped_prior = base.copy(), base.copy()
        scope = scope_key(program)
        for column, course_id in enumerate(course_ids):
            title = normalize(course_title(courses[course_id]))
            coverage["candidate_rows"] += 1
            if global_memory.get(title):
                global_prior[:, column] = aggregate(np.asarray(query_vectors), global_memory[title], vectors)
                coverage["global_rows"] += 1
            if scoped_memory.get((scope, title)):
                scoped_prior[:, column] = aggregate(np.asarray(query_vectors), scoped_memory[(scope, title)], vectors)
                coverage["scoped_rows"] += 1
        positions = {key: position for position, key in enumerate(course_ids)}
        for row, lo_id in enumerate(lo_ids):
            relevant = {positions[key] for key in links[lo_id] if key in positions}
            rows.append((base[row], global_prior[row], scoped_prior[row], relevant))
    coverage["global_fraction"] = coverage["global_rows"] / coverage["candidate_rows"] if coverage["candidate_rows"] else 0
    coverage["scoped_fraction"] = coverage["scoped_rows"] / coverage["candidate_rows"] if coverage["candidate_rows"] else 0
    return rows, dict(coverage)


def ranking_metrics(rows):
    values: dict[str, list[float]] = defaultdict(list)
    for scores, relevant in rows:
        ranking = np.argsort(-scores)
        for k in (1, 3, 5, 10):
            hits = sum(int(item) in relevant for item in ranking[:k])
            recall = hits / len(relevant)
            oracle = min(k, len(relevant)) / len(relevant)
            values[f"recall_at_{k}"].append(recall)
            values[f"hit_rate_at_{k}"].append(float(hits > 0))
            values[f"oracle_normalized_recall_at_{k}"].append(recall / oracle if oracle else 0.0)
        first = next((position + 1 for position, item in enumerate(ranking) if int(item) in relevant), None)
        values["mrr"].append(1 / first if first else 0.0)
        dcg = sum((1 if int(item) in relevant else 0) / math.log2(position + 2) for position, item in enumerate(ranking[:10]))
        ideal = sum(1 / math.log2(position + 2) for position in range(min(len(relevant), 10)))
        values["ndcg_at_10"].append(dcg / ideal if ideal else 0.0)
    return {key: float(np.mean(value)) for key, value in values.items()}


def blended(rows, global_weight, scoped_weight):
    base_weight = 1.0 - global_weight - scoped_weight
    return [(base_weight * base + global_weight * global_prior + scoped_weight * scoped_prior, relevant) for base, global_prior, scoped_prior, relevant in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--model", default=str(ROOT / "models" / "epvo-sbert-ranking-loss-pilot"))
    parser.add_argument("--output", default=str(ROOT / "experiment-results" / "epvo-ranking-scoped-memory" / "metrics.json"))
    parser.add_argument("--programmes", type=int, default=120)
    parser.add_argument("--per-key-limit", type=int, default=32)
    parser.add_argument("--batch-size", type=int, default=24)
    args = parser.parse_args()

    path = Path(args.data)
    selected = select_splits(path, {"validation": args.programmes, "test": args.programmes}, "ranking-v1")
    titles, scope_titles = target_titles(selected), target_scope_titles(selected)
    global_memory, scoped_memory, memory_stats = collect_memory(path, titles, scope_titles, args.per_key_limit)
    unique_texts = sorted({text for memory in (global_memory, scoped_memory) for values in memory.values() for text in values})
    model = SentenceTransformer(args.model, device="cuda", local_files_only=True)
    encoded = model.encode(unique_texts, batch_size=args.batch_size, normalize_embeddings=True, show_progress_bar=True)
    vectors = dict(zip(unique_texts, encoded))
    validation_rows, validation_coverage = score_split(selected["validation"], model, global_memory, scoped_memory, vectors, args.batch_size)
    global_grid = [0.0, 0.1, 0.2, 0.3, 0.4]
    scoped_grid = [round(value, 2) for value in np.linspace(0, 0.8, 17)]
    validation_results = []
    for global_weight in global_grid:
        for scoped_weight in scoped_grid:
            if global_weight + scoped_weight > 0.8:
                continue
            result = ranking_metrics(blended(validation_rows, global_weight, scoped_weight))
            objective = result["recall_at_10"] + 0.05 * result["ndcg_at_10"] + 0.02 * result["mrr"]
            validation_results.append({"global_weight": global_weight, "scoped_weight": scoped_weight, "objective": objective, **result})
    best = max(validation_results, key=lambda row: (row["objective"], row["recall_at_10"]))
    test_rows, test_coverage = score_split(selected["test"], model, global_memory, scoped_memory, vectors, args.batch_size)
    baseline = ranking_metrics(blended(test_rows, 0.0, 0.0))
    frozen = ranking_metrics(blended(test_rows, best["global_weight"], best["scoped_weight"]))
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "train-only global and exact EPVO-group course expert memory",
        "model": args.model, "split_policy": "programme-level frozen split",
        "memory": memory_stats, "validation_coverage": validation_coverage, "test_coverage": test_coverage,
        "validation_results": validation_results,
        "selected_global_weight": best["global_weight"], "selected_scoped_weight": best["scoped_weight"],
        "validation_selected": best, "frozen_test_baseline": baseline, "frozen_test": frozen,
        "frozen_test_delta": {key: frozen[key] - baseline[key] for key in frozen},
        "production_model_changed": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
