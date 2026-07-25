"""Select an SBERT ensemble on validation and evaluate frozen test efficiently."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "experiment-results" / "epvo-expert-labels" / "course_lo_pairs.jsonl"


def collect(split: str, programme_limit: int):
    selected = set()
    candidates = set()
    with DATA.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("split") == split:
                program = str(row["program_id"])
                candidates.add(
                    (hashlib.sha256(f"ranking-v1:{split}:{program}".encode()).hexdigest(), program)
                )
    selected = {program for _, program in sorted(candidates)[:programme_limit]}
    data = defaultdict(lambda: {"courses": {}, "los": {}, "links": defaultdict(set)})
    with DATA.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            program = str(row.get("program_id"))
            if program not in selected:
                continue
            course_id, lo_id = str(row["course_id"]), str(row["lo_id"])
            title = row.get("course_title") or {}
            description = row.get("course_description") or {}
            lo_text = row.get("lo_text") or {}
            data[program]["courses"][course_id] = " | ".join(
                filter(
                    None,
                    (
                        title.get("ru") or title.get("kz") or title.get("en"),
                        description.get("ru") or description.get("kz") or description.get("en"),
                    ),
                )
            )
            data[program]["los"][lo_id] = (
                lo_text.get("ru") or lo_text.get("kz") or lo_text.get("en") or ""
            )
            if row.get("declared_link", True):
                data[program]["links"][lo_id].add(course_id)
    return data


def matrices(model: SentenceTransformer, data: dict):
    result = {}
    for program in sorted(data):
        block = data[program]
        course_ids = list(block["courses"])
        lo_ids = [key for key in block["los"] if block["links"].get(key)]
        if len(course_ids) < 2 or not lo_ids:
            continue
        courses = model.encode(
            [block["courses"][key] for key in course_ids],
            batch_size=48,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        los = model.encode(
            [block["los"][key] for key in lo_ids],
            batch_size=48,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        result[program] = (course_ids, lo_ids, np.asarray(los) @ np.asarray(courses).T)
    return result


def metrics(data: dict, left: dict, right: dict, weight: float):
    recall5, recall10, reciprocal, ndcg10 = [], [], [], []
    for program in sorted(set(left) & set(right)):
        course_ids, lo_ids, left_scores = left[program]
        right_course_ids, right_lo_ids, right_scores = right[program]
        if course_ids != right_course_ids or lo_ids != right_lo_ids:
            raise RuntimeError("Model matrix order mismatch")
        scores = (1 - weight) * left_scores + weight * right_scores
        for index, lo_id in enumerate(lo_ids):
            relevant = data[program]["links"][lo_id]
            ranking = [course_ids[position] for position in np.argsort(-scores[index])]
            recall5.append(sum(item in relevant for item in ranking[:5]) / len(relevant))
            recall10.append(sum(item in relevant for item in ranking[:10]) / len(relevant))
            first = next((rank + 1 for rank, item in enumerate(ranking) if item in relevant), None)
            reciprocal.append(1 / first if first else 0)
            dcg = sum(
                (1 if item in relevant else 0) / math.log2(rank + 2)
                for rank, item in enumerate(ranking[:10])
            )
            ideal = sum(1 / math.log2(rank + 2) for rank in range(min(len(relevant), 10)))
            ndcg10.append(dcg / ideal if ideal else 0)
    return {
        "programmes": len(set(left) & set(right)),
        "queries": len(recall5),
        "recall_at_5": float(np.mean(recall5)),
        "recall_at_10": float(np.mean(recall10)),
        "mrr": float(np.mean(reciprocal)),
        "ndcg_at_10": float(np.mean(ndcg10)),
    }


def objective(value: dict) -> float:
    return (
        0.35 * value["recall_at_5"]
        + 0.15 * value["recall_at_10"]
        + 0.25 * value["mrr"]
        + 0.25 * value["ndcg_at_10"]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="models/epvo-sbert-ranking-loss-pilot")
    parser.add_argument("--candidate", default="models/epvo-sbert-cached-ranker-12k-v2")
    parser.add_argument("--output", default="experiment-results/epvo-ranking-ensemble-validation")
    parser.add_argument("--programs", type=int, default=120)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    output = ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)

    base = SentenceTransformer(args.base, device=args.device, local_files_only=True)
    candidate = SentenceTransformer(args.candidate, device=args.device, local_files_only=True)
    validation_data = collect("validation", args.programs)
    validation_base = matrices(base, validation_data)
    validation_candidate = matrices(candidate, validation_data)
    weights = [round(value / 20, 2) for value in range(0, 11)]
    validation_results = []
    for weight in weights:
        value = metrics(validation_data, validation_base, validation_candidate, weight)
        validation_results.append({"weight": weight, "objective": objective(value), **value})
    selected = max(validation_results, key=lambda item: item["objective"])

    test_data = collect("test", args.programs)
    test_base = matrices(base, test_data)
    test_candidate = matrices(candidate, test_data)
    frozen_test = metrics(
        test_data, test_base, test_candidate, float(selected["weight"])
    )
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selection_split": "validation",
        "final_evaluation_split": "test",
        "programs_per_split": args.programs,
        "base": args.base,
        "candidate": args.candidate,
        "weights": weights,
        "objective": "0.35 R@5 + 0.15 R@10 + 0.25 MRR + 0.25 nDCG@10",
        "validation_results": validation_results,
        "selected_weight": selected["weight"],
        "selected_validation_objective": selected["objective"],
        "frozen_test": frozen_test,
        "production_model_changed": False,
    }
    (output / "selection-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
