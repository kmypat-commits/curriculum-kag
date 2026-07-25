"""Evaluate a train-only EPVO expert-memory prior on frozen ranking splits."""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

LOCAL_SITE = Path(__file__).resolve().parents[1] / "venv" / "Lib" / "site-packages"
if LOCAL_SITE.exists():
    sys.path.insert(0, str(LOCAL_SITE))

import numpy as np
from sentence_transformers import SentenceTransformer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "experiment-results" / "epvo-link-context-dataset" / "programs.jsonl"


def localized(value: dict) -> str:
    return str(value.get("ru") or value.get("kz") or value.get("en") or "").strip()


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def course_title(course: dict) -> str:
    return localized(course.get("title") or {})


def course_text(course: dict) -> str:
    return " | ".join(filter(None, (course_title(course), localized(course.get("description") or {}))))


def select_splits(path: Path, counts: dict[str, int], seed_prefix: str) -> dict[str, list[dict]]:
    heaps: dict[str, list[tuple[int, int, dict]]] = {split: [] for split in counts}
    serial = 0
    with path.open(encoding="utf-8") as source:
        for line in source:
            program = json.loads(line)
            split = str(program.get("split"))
            if split not in counts:
                continue
            serial += 1
            rank = int(hashlib.sha256(f"{seed_prefix}:{split}:{program.get('program_id')}".encode()).hexdigest(), 16)
            item = (-rank, serial, program)
            heap = heaps[split]
            if len(heap) < counts[split]:
                heapq.heappush(heap, item)
            elif rank < -heap[0][0]:
                heapq.heapreplace(heap, item)
    return {split: [program for neg, _, program in sorted(heap, key=lambda item: -item[0])] for split, heap in heaps.items()}


def target_titles(selected: dict[str, list[dict]]) -> set[str]:
    return {
        normalize(course_title(course))
        for programmes in selected.values()
        for program in programmes
        for course in program.get("courses") or []
        if course_title(course)
    }


def collect_train_memory(path: Path, targets: set[str], per_course_limit: int) -> tuple[dict[str, list[str]], dict]:
    memory: dict[str, dict[str, str]] = defaultdict(dict)
    programmes = edges_seen = retained = 0
    with path.open(encoding="utf-8") as source:
        for line in source:
            program = json.loads(line)
            if program.get("split") != "train":
                continue
            programmes += 1
            courses = {
                str(item["id"]): normalize(course_title(item))
                for item in program.get("courses") or []
                if normalize(course_title(item)) in targets
            }
            if not courses:
                continue
            outcomes = {
                str(item["id"]): localized(item.get("text") or {})
                for item in program.get("outcomes") or []
                if localized(item.get("text") or {})
            }
            for course_id, lo_id in program.get("positive_edges") or []:
                edges_seen += 1
                title, text = courses.get(str(course_id)), outcomes.get(str(lo_id))
                if not title or not text:
                    continue
                key = hashlib.sha1(normalize(text).encode("utf-8")).hexdigest()
                bucket = memory[title]
                bucket[key] = text
                if len(bucket) > per_course_limit:
                    del bucket[max(bucket)]
                retained += 1
    result = {title: list(values.values()) for title, values in memory.items()}
    return result, {
        "train_programmes_scanned": programmes,
        "target_titles": len(targets),
        "titles_with_train_memory": len(result),
        "edges_seen": edges_seen,
        "matching_edges_seen": retained,
        "unique_evidence_los": sum(map(len, result.values())),
        "per_course_limit": per_course_limit,
    }


def metrics(rows: list[tuple[np.ndarray, set[int]]]) -> dict:
    values: dict[str, list[float]] = defaultdict(list)
    for scores, relevant in rows:
        ranking = np.argsort(-scores)
        for k in (1, 3, 5, 10):
            values[f"recall_at_{k}"].append(sum(int(pos) in relevant for pos in ranking[:k]) / len(relevant))
        first = next((position + 1 for position, item in enumerate(ranking) if int(item) in relevant), None)
        values["mrr"].append(1 / first if first else 0.0)
        dcg = sum((1 if int(item) in relevant else 0) / math.log2(position + 2) for position, item in enumerate(ranking[:10]))
        ideal = sum(1 / math.log2(position + 2) for position in range(min(len(relevant), 10)))
        values["ndcg_at_10"].append(dcg / ideal if ideal else 0.0)
    return {key: float(np.mean(value)) for key, value in values.items()}


def score_split(programmes: list[dict], model: SentenceTransformer, memory: dict[str, list[str]], vectors: dict[str, np.ndarray], batch_size: int):
    rows: list[tuple[np.ndarray, np.ndarray, set[int]]] = []
    memory_candidates = total_candidates = 0
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
        base_scores = np.asarray(query_vectors) @ np.asarray(course_vectors).T
        prior_scores = base_scores.copy()
        for column, course_id in enumerate(course_ids):
            evidence = memory.get(normalize(course_title(courses[course_id])))
            total_candidates += 1
            if not evidence:
                continue
            memory_candidates += 1
            matrix = np.asarray([vectors[text] for text in evidence])
            similarity = np.asarray(query_vectors) @ matrix.T
            top = np.sort(similarity, axis=1)[:, -min(3, similarity.shape[1]):]
            prior_scores[:, column] = 0.75 * similarity.max(axis=1) + 0.25 * top.mean(axis=1)
        positions = {key: pos for pos, key in enumerate(course_ids)}
        for row, lo_id in enumerate(lo_ids):
            relevant = {positions[key] for key in links[lo_id] if key in positions}
            rows.append((base_scores[row], prior_scores[row], relevant))
    return rows, {"memory_candidate_fraction": memory_candidates / total_candidates if total_candidates else 0.0, "candidate_rows": total_candidates, "memory_candidate_rows": memory_candidates}


def blended(rows, weight: float):
    return [((1 - weight) * base + weight * prior, relevant) for base, prior, relevant in rows]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--model", default=str(ROOT / "models" / "epvo-sbert-ranking-loss-pilot"))
    parser.add_argument("--output", default=str(ROOT / "experiment-results" / "epvo-ranking-expert-memory" / "metrics.json"))
    parser.add_argument("--programmes", type=int, default=120)
    parser.add_argument("--per-course-limit", type=int, default=32)
    parser.add_argument("--batch-size", type=int, default=24)
    args = parser.parse_args()

    path = Path(args.data)
    selected = select_splits(path, {"validation": args.programmes, "test": args.programmes}, "ranking-v1")
    targets = target_titles(selected)
    memory, memory_stats = collect_train_memory(path, targets, args.per_course_limit)
    unique_texts = sorted({text for values in memory.values() for text in values})
    model = SentenceTransformer(args.model, device="cuda", local_files_only=True)
    encoded = model.encode(unique_texts, batch_size=args.batch_size, normalize_embeddings=True, show_progress_bar=True)
    vectors = {text: vector for text, vector in zip(unique_texts, encoded)}
    validation_rows, validation_coverage = score_split(selected["validation"], model, memory, vectors, args.batch_size)
    weights = [round(value, 2) for value in np.linspace(0, 1, 21)]
    validation_results = []
    for weight in weights:
        result = metrics(blended(validation_rows, weight))
        objective = result["recall_at_10"] + 0.05 * result["ndcg_at_10"] + 0.02 * result["mrr"]
        validation_results.append({"weight": weight, "objective": objective, **result})
    selected_weight = max(validation_results, key=lambda row: (row["objective"], row["recall_at_10"]))["weight"]
    test_rows, test_coverage = score_split(selected["test"], model, memory, vectors, args.batch_size)
    baseline = metrics(blended(test_rows, 0.0))
    frozen = metrics(blended(test_rows, selected_weight))
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "train-only exact-canonical-title expert memory; max/top3 historical LO similarity",
        "model": args.model, "split_policy": "programme-level frozen split",
        "memory": memory_stats, "validation_coverage": validation_coverage,
        "test_coverage": test_coverage, "validation_results": validation_results,
        "selected_weight": selected_weight, "frozen_test_baseline": baseline,
        "frozen_test": frozen,
        "frozen_test_delta": {key: frozen[key] - baseline[key] for key in frozen},
        "production_model_changed": False,
    }
    save_path = Path(args.output)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
