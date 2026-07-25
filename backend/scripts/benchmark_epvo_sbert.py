"""Benchmark local multilingual SBERT on unseen EPVO programs."""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics import accuracy_score, average_precision_score, f1_score, precision_score, recall_score, roc_auc_score


def text(values): return values.get("ru") or values.get("kz") or values.get("en") or ""


def samples(path, split, limit, include_context=False):
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            program = json.loads(line)
            if program.get("split") != split: continue
            courses = {str(x["id"]): x for x in program["courses"]}; outcomes = {str(x["id"]): x for x in program["outcomes"]}
            edges = {(str(a), str(b)) for a, b in program["positive_edges"]}
            by_course = {}
            for course_id, lo_id in edges: by_course.setdefault(course_id, set()).add(lo_id)
            rng = random.Random(f"{program['program_id']}:sbert:42")
            for course_id, positive_ids in by_course.items():
                if course_id not in courses: continue
                negative_ids = [lo_id for lo_id in outcomes if lo_id not in positive_ids]
                if not negative_ids: continue
                positive_id = rng.choice(sorted(positive_ids)); negative_id = rng.choice(negative_ids)
                course = courses[course_id]
                context = ""
                if include_context:
                    context = " ЦЕЛЬ ПРОГРАММЫ: " + text(program.get("program_goal") or {})
                    context += " НАПРАВЛЕНИЕ: " + text(program.get("training_direction") or {})
                    context += " ГРУППА: " + text(program.get("program_group") or {})
                course_text = text(course["title"]) + ". " + text(course["description"]) + context
                rows.append((course_text, text(outcomes[positive_id]["text"]), 1))
                rows.append((course_text, text(outcomes[negative_id]["text"]), 0))
                if len(rows) >= limit: return rows
    return rows


def metrics(actual, scores, threshold):
    predicted = scores >= threshold
    return {"examples": len(actual), "roc_auc": float(roc_auc_score(actual, scores)), "pr_auc": float(average_precision_score(actual, scores)), "threshold": float(threshold), "accuracy": float(accuracy_score(actual, predicted)), "precision": float(precision_score(actual, predicted)), "recall": float(recall_score(actual, predicted)), "f1": float(f1_score(actual, predicted))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiment-results/epvo-link-dataset/programs.jsonl")
    parser.add_argument("--model", default="models/paraphrase-multilingual-mpnet-base-v2")
    parser.add_argument("--output", default="experiment-results/epvo-sbert-benchmark")
    parser.add_argument("--limit", type=int, default=6000); parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--context", action="store_true")
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    args = parser.parse_args(); source, output = Path(args.input), Path(args.output); output.mkdir(parents=True, exist_ok=True)
    model = SentenceTransformer(args.model, local_files_only=True, device=args.device)
    result = {}
    stored = {}
    for split in ("validation", "test"):
        rows = samples(source, split, args.limit, args.context)
        course_vectors = model.encode([x[0] for x in rows], batch_size=args.batch_size, normalize_embeddings=True, show_progress_bar=True)
        outcome_vectors = model.encode([x[1] for x in rows], batch_size=args.batch_size, normalize_embeddings=True, show_progress_bar=True)
        scores = np.sum(course_vectors * outcome_vectors, axis=1); actual = np.asarray([x[2] for x in rows])
        stored[split] = (actual, scores)
    validation_actual, validation_scores = stored["validation"]
    candidates = np.linspace(float(validation_scores.min()), float(validation_scores.max()), 301)
    threshold = max(candidates, key=lambda value: f1_score(validation_actual, validation_scores >= value))
    for split, (actual, scores) in stored.items(): result[split] = metrics(actual, scores, threshold)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "model": args.model, "device": args.device, "program_context": args.context, "sampling": "one positive and one within-program negative per course", **result}
    (output / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__": main()
