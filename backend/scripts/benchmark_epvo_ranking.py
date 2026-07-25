"""Evaluate course retrieval on frozen test programmes: Recall@K, MRR, nDCG."""
import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "experiment-results" / "epvo-expert-labels" / "course_lo_pairs.jsonl"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--model", default=str(ROOT / "models" / "epvo-sbert-finetuned-40k"))
    parser.add_argument("--candidate-model")
    parser.add_argument("--candidate-weight", type=float, default=0.0)
    parser.add_argument("--output", default=str(ROOT / "experiment-results" / "epvo-ranking-benchmark" / "metrics.json"))
    parser.add_argument("--programs", type=int, default=80)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--seed-prefix", default="ranking-v1")
    args = parser.parse_args()
    selected = []
    with open(args.data, encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("split") != args.split:
                continue
            program = str(row["program_id"])
            score = hashlib.sha256(f"{args.seed_prefix}:{args.split}:{program}".encode()).hexdigest()
            selected.append((score, program))
    programmes = {program for _, program in sorted(set(selected))[:args.programs]}
    data = defaultdict(lambda: {"courses": {}, "los": {}, "links": defaultdict(set)})
    with open(args.data, encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            program = str(row.get("program_id"))
            if program not in programmes:
                continue
            course_id, lo_id = str(row["course_id"]), str(row["lo_id"])
            title = row.get("course_title") or {}
            description = row.get("course_description") or {}
            lo_text = row.get("lo_text") or {}
            data[program]["courses"][course_id] = " | ".join(filter(None, [title.get("ru") or title.get("kz") or title.get("en"), description.get("ru") or description.get("kz") or description.get("en")]))
            data[program]["los"][lo_id] = lo_text.get("ru") or lo_text.get("kz") or lo_text.get("en") or ""
            if row.get("declared_link", True):
                data[program]["links"][lo_id].add(course_id)
    model = SentenceTransformer(args.model, device=args.device)
    candidate = (
        SentenceTransformer(args.candidate_model, device=args.device)
        if args.candidate_model and args.candidate_weight > 0
        else None
    )
    recall5, recall10, reciprocal, ndcg10 = [], [], [], []
    query_count = 0
    for program in sorted(data):
        block = data[program]
        course_ids = list(block["courses"])
        if len(course_ids) < 2:
            continue
        course_vectors = model.encode([block["courses"][key] for key in course_ids], batch_size=48, normalize_embeddings=True, show_progress_bar=False)
        lo_ids = [key for key in block["los"] if block["links"].get(key)]
        if not lo_ids:
            continue
        lo_vectors = model.encode([block["los"][key] for key in lo_ids], batch_size=48, normalize_embeddings=True, show_progress_bar=False)
        scores = np.asarray(lo_vectors) @ np.asarray(course_vectors).T
        if candidate is not None:
            candidate_courses = candidate.encode([block["courses"][key] for key in course_ids], batch_size=48, normalize_embeddings=True, show_progress_bar=False)
            candidate_los = candidate.encode([block["los"][key] for key in lo_ids], batch_size=48, normalize_embeddings=True, show_progress_bar=False)
            candidate_scores = np.asarray(candidate_los) @ np.asarray(candidate_courses).T
            scores = (1 - args.candidate_weight) * scores + args.candidate_weight * candidate_scores
        for index, lo_id in enumerate(lo_ids):
            relevant = block["links"][lo_id]
            ranking = [course_ids[i] for i in np.argsort(-scores[index])]
            hits5 = sum(item in relevant for item in ranking[:5])
            hits10 = sum(item in relevant for item in ranking[:10])
            recall5.append(hits5 / len(relevant)); recall10.append(hits10 / len(relevant))
            first = next((position + 1 for position, item in enumerate(ranking) if item in relevant), None)
            reciprocal.append(1 / first if first else 0)
            dcg = sum((1 if item in relevant else 0) / math.log2(position + 2) for position, item in enumerate(ranking[:10]))
            ideal = sum(1 / math.log2(position + 2) for position in range(min(len(relevant), 10)))
            ndcg10.append(dcg / ideal if ideal else 0)
            query_count += 1
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(), "model": args.model,
        "candidate_model": args.candidate_model, "candidate_weight": args.candidate_weight, "device": args.device,
        "seed_policy": f"sha256({args.seed_prefix}:{args.split}:program_id)",
        "split": args.split, "programmes": len(data), "queries": query_count,
        "recall_at_5": float(np.mean(recall5)), "recall_at_10": float(np.mean(recall10)),
        "mrr": float(np.mean(reciprocal)), "ndcg_at_10": float(np.mean(ndcg10)),
    }
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
