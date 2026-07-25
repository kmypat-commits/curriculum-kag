"""Run a transparent SBERT vs feature-hash retrieval benchmark.

Without an expert-labelled CSV this is only a smoke benchmark.  A gold CSV
must contain: query, relevant_course_code.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import SessionLocal
from app.models.course import Course


def feature_hash(text, dimension):
    vector = np.zeros(dimension, dtype=np.float32)
    for token in re.findall(r"[\w-]+", text.lower(), flags=re.UNICODE):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        vector[int.from_bytes(digest[:4], "little") % dimension] += 1 if digest[4] % 2 == 0 else -1
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def load_gold(path):
    with open(path, encoding="utf-8-sig", newline="") as stream:
        return [(row["query"], row["relevant_course_code"]) for row in csv.DictReader(stream)]


def recall_at_k(query_vectors, course_vectors, gold, course_codes, k):
    scores = query_vectors @ course_vectors.T
    hits = 0
    ranks = []
    for index, (_, relevant_code) in enumerate(gold):
        order = np.argsort(-scores[index])
        ranked_codes = [course_codes[item] for item in order]
        if relevant_code in ranked_codes:
            rank = ranked_codes.index(relevant_code) + 1
            ranks.append(rank)
            hits += int(rank <= k)
    return hits / max(len(gold), 1), sum(1 / rank for rank in ranks) / max(len(gold), 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", help="CSV with query,relevant_course_code")
    parser.add_argument("--model", default=settings.EMBEDDING_MODEL_NAME)
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--output", default="experiment-results/embedding-benchmark.json")
    args = parser.parse_args()
    if not args.gold:
        raise SystemExit("Expert-labelled --gold CSV is required for a scientific comparison")

    gold = load_gold(args.gold)
    session = SessionLocal()
    courses = session.query(Course).order_by(Course.id).all()
    session.close()
    course_codes = [course.course_id for course in courses]
    course_texts = [
        " ".join(filter(None, [
            course.title, course.description or "",
            " ".join(course.topics or []), " ".join(course.learning_outcomes or []),
        ]))
        for course in courses
    ]
    queries = [item[0] for item in gold]

    started = time.perf_counter()
    hash_courses = np.vstack([feature_hash(text, settings.EMBEDDING_DIMENSION) for text in course_texts])
    hash_queries = np.vstack([feature_hash(text, settings.EMBEDDING_DIMENSION) for text in queries])
    hash_seconds = time.perf_counter() - started

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(args.model)
    started = time.perf_counter()
    sbert_courses = model.encode(course_texts, normalize_embeddings=True, convert_to_numpy=True)
    sbert_queries = model.encode(queries, normalize_embeddings=True, convert_to_numpy=True)
    sbert_seconds = time.perf_counter() - started

    hash_recall, hash_mrr = recall_at_k(hash_queries, hash_courses, gold, course_codes, args.k)
    sbert_recall, sbert_mrr = recall_at_k(sbert_queries, sbert_courses, gold, course_codes, args.k)
    result = {
        "gold_pairs": len(gold), "courses": len(courses), "k": args.k,
        "feature_hash": {"recall_at_k": hash_recall, "mrr": hash_mrr, "seconds": hash_seconds},
        "sbert": {"model": args.model, "dimension": int(sbert_courses.shape[1]), "recall_at_k": sbert_recall, "mrr": sbert_mrr, "seconds": sbert_seconds},
        "accepted": sbert_recall > hash_recall or (sbert_recall == hash_recall and sbert_mrr > hash_mrr),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
