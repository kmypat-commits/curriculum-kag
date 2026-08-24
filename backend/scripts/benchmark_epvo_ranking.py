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


def _localized_text(value: object) -> str:
    """Choose a deterministic non-empty text across the EPVO languages."""
    if isinstance(value, dict):
        return " | ".join(
            str(value.get(key) or "").strip()
            for key in ("ru", "kz", "kk", "en")
            if str(value.get(key) or "").strip()
        )
    return str(value or "").strip()


def _course_text(course: dict) -> str:
    title = _localized_text(course.get("title"))
    description = _localized_text(course.get("description"))
    return " | ".join(filter(None, (title, description)))


def _outcome_text(outcome: dict) -> str:
    return _localized_text(outcome.get("text") or outcome.get("description") or outcome.get("title"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--model", default=str(ROOT / "models" / "epvo-sbert-finetuned-40k"))
    parser.add_argument("--candidate-model")
    parser.add_argument("--candidate-weight", type=float, default=0.0)
    parser.add_argument("--output", default=str(ROOT / "experiment-results" / "epvo-ranking-benchmark" / "metrics.json"))
    parser.add_argument("--programs", type=int, default=80)
    parser.add_argument(
        "--programmes-data",
        help="Programme-level JSONL with all courses and expert_edges. Defaults to programs.jsonl beside --data when present.",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--seed-prefix", default="ranking-v1")
    parser.add_argument(
        "--min-expert-score", type=float, default=0.5,
        help="Keep only EPVO links at or above this graded expert strength (0.5 = medium/high by default).",
    )
    args = parser.parse_args()
    programme_path = Path(args.programmes_data) if args.programmes_data else Path(args.data).with_name("programs.jsonl")
    use_programme_rows = programme_path.is_file()
    selected = []
    text_rows = 0
    source_path = programme_path if use_programme_rows else Path(args.data)
    with source_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("split") != args.split:
                continue
            if use_programme_rows:
                has_text = any(_course_text(course) for course in row.get("courses") or []) and any(
                    _outcome_text(outcome) for outcome in row.get("outcomes") or []
                )
            else:
                has_text = bool(row.get("course_title") or row.get("course_description") or row.get("lo_text"))
            if has_text:
                text_rows += 1
            program = str(row["program_id"])
            score = hashlib.sha256(f"{args.seed_prefix}:{args.split}:{program}".encode()).hexdigest()
            selected.append((score, program))
    if selected and text_rows == 0:
        raise SystemExit(
            "Ranking dataset has no course/LO text. Re-export it with "
            "export_epvo_ranking_dataset_postgres.py before measuring SBERT."
        )
    programmes = {program for _, program in sorted(set(selected))[:args.programs]}
    data = defaultdict(lambda: {"courses": {}, "los": {}, "links": defaultdict(set), "weights": defaultdict(dict)})
    if use_programme_rows:
        # Programme-level rows retain unlinked courses.  Ranking against this
        # complete candidate pool avoids the optimistic bias of the legacy
        # positive-pairs-only export.
        with programme_path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                program = str(row.get("program_id"))
                if program not in programmes:
                    continue
                for course in row.get("courses") or []:
                    course_id = str(course.get("id") or course.get("course_id") or "")
                    text_value = _course_text(course)
                    if course_id and text_value:
                        data[program]["courses"][course_id] = text_value
                for outcome in row.get("outcomes") or []:
                    lo_id = str(outcome.get("id") or outcome.get("lo_id") or "")
                    text_value = _outcome_text(outcome)
                    if lo_id and text_value:
                        data[program]["los"][lo_id] = text_value
                expert_scores = {
                    (str(edge.get("course_id")), str(edge.get("lo_id"))): float(edge.get("score") or 0.0)
                    for edge in row.get("expert_edges") or []
                    if edge.get("course_id") is not None and edge.get("lo_id") is not None
                }
                for edge in row.get("positive_edges") or []:
                    if not isinstance(edge, (list, tuple)) or len(edge) < 2:
                        continue
                    course_id, lo_id = str(edge[0]), str(edge[1])
                    score = expert_scores.get((course_id, lo_id), 1.0)
                    if course_id in data[program]["courses"] and lo_id in data[program]["los"] and score >= args.min_expert_score:
                        data[program]["links"][lo_id].add(course_id)
                        data[program]["weights"][lo_id][course_id] = score
    else:
        with Path(args.data).open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                program = str(row.get("program_id"))
                if program not in programmes:
                    continue
                course_id, lo_id = str(row["course_id"]), str(row["lo_id"])
                title = row.get("course_title") or {}
                description = row.get("course_description") or {}
                lo_text = row.get("lo_text") or {}
                data[program]["courses"][course_id] = " | ".join(filter(None, [_localized_text(title), _localized_text(description)]))
                data[program]["los"][lo_id] = _localized_text(lo_text)
                if row.get("declared_link", True) and float(row.get("expert_score") or 0.0) >= args.min_expert_score:
                    data[program]["links"][lo_id].add(course_id)
                    raw_score = row.get("expert_score")
                    data[program]["weights"][lo_id][course_id] = float(raw_score) if raw_score is not None else 1.0
    model = SentenceTransformer(args.model, device=args.device)
    candidate = (
        SentenceTransformer(args.candidate_model, device=args.device)
        if args.candidate_model and args.candidate_weight > 0
        else None
    )
    recall5, recall10, reciprocal, ndcg10, graded_ndcg10 = [], [], [], [], []
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
            weights = block["weights"].get(lo_id, {})
            graded_dcg = sum(float(weights.get(item, 0.0)) / math.log2(position + 2) for position, item in enumerate(ranking[:10]))
            ideal_weights = sorted((float(value) for value in weights.values()), reverse=True)[:10]
            graded_ideal = sum(value / math.log2(position + 2) for position, value in enumerate(ideal_weights))
            graded_ndcg10.append(graded_dcg / graded_ideal if graded_ideal else 0)
            query_count += 1
    if query_count == 0:
        raise SystemExit(
            "No benchmark queries remain after programme/text/expert-score filtering. "
            "Check the split, programme-level export, and --min-expert-score."
        )
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(), "model": args.model,
        "candidate_model": args.candidate_model, "candidate_weight": args.candidate_weight, "device": args.device,
        "candidate_pool_source": "programme_level" if use_programme_rows else "positive_pairs_legacy",
        "seed_policy": f"sha256({args.seed_prefix}:{args.split}:program_id)",
        "split": args.split, "min_expert_score": args.min_expert_score,
        "programmes": len(data), "queries": query_count,
        "recall_at_5": float(np.mean(recall5)), "recall_at_10": float(np.mean(recall10)),
        "mrr": float(np.mean(reciprocal)), "ndcg_at_10": float(np.mean(ndcg10)),
        "graded_ndcg_at_10": float(np.mean(graded_ndcg10)),
    }
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
