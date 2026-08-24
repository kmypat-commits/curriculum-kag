"""Leakage-safe lexical/ranking reranker benchmark for the EPVO corpus.

The vectorizer is fitted only on train programmes.  Test programmes provide
only the candidate pool, LO query and held-out declared/expert edges.  This
script is intentionally separate from the production planner: it produces
metrics for an experiment and never changes model or database state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def text_value(value: object) -> str:
    if isinstance(value, dict):
        return " | ".join(
            str(value.get(key) or "").strip()
            for key in ("ru", "kz", "kk", "en")
            if str(value.get(key) or "").strip()
        )
    return str(value or "").strip()


def course_text(row: dict) -> str:
    return " | ".join(filter(None, (text_value(row.get("title")), text_value(row.get("description")))))


def outcome_text(row: dict) -> str:
    return text_value(row.get("text") or row.get("description") or row.get("title"))


def title_key(row: dict) -> str:
    """Language-independent key used only for train-set course anchors."""
    title = text_value(row.get("title"))
    return " ".join(TOKEN_RE.findall(title.casefold()))


def selected_programmes(rows: list[dict], split: str, limit: int) -> set[str]:
    scored = []
    for row in rows:
        if row.get("split") != split:
            continue
        if not any(course_text(course) for course in row.get("courses") or []):
            continue
        if not any(outcome_text(outcome) for outcome in row.get("outcomes") or []):
            continue
        program = str(row.get("program_id"))
        scored.append((hashlib.sha256(f"ranking-v1:{split}:{program}".encode()).hexdigest(), program))
    return {program for _, program in sorted(scored)[:limit]}


def rank_metrics(block: dict[str, dict], scores: np.ndarray) -> dict[str, float]:
    recall5: list[float] = []
    recall10: list[float] = []
    reciprocal: list[float] = []
    ndcg10: list[float] = []
    queries = 0
    for row_index, lo_id in enumerate(block["lo_ids"]):
        relevant = block["links"].get(lo_id, set())
        if not relevant:
            continue
        ranking = [block["course_ids"][i] for i in np.argsort(-scores[row_index])]
        recall5.append(sum(item in relevant for item in ranking[:5]) / len(relevant))
        recall10.append(sum(item in relevant for item in ranking[:10]) / len(relevant))
        first = next((index + 1 for index, item in enumerate(ranking) if item in relevant), None)
        reciprocal.append(1 / first if first else 0.0)
        dcg = sum((1 if item in relevant else 0) / math.log2(index + 2) for index, item in enumerate(ranking[:10]))
        ideal = sum(1 / math.log2(index + 2) for index in range(min(len(relevant), 10)))
        ndcg10.append(dcg / ideal if ideal else 0.0)
        queries += 1
    if not queries:
        return {"queries": 0, "recall_at_5": 0.0, "recall_at_10": 0.0, "mrr": 0.0, "ndcg_at_10": 0.0}
    return {
        "queries": queries,
        "recall_at_5": float(np.mean(recall5)),
        "recall_at_10": float(np.mean(recall10)),
        "mrr": float(np.mean(reciprocal)),
        "ndcg_at_10": float(np.mean(ndcg10)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--programs", type=int, default=80)
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--min-expert-score", type=float, default=0.5)
    parser.add_argument("--sbert-model", type=Path, help="Optional SBERT model for a leakage-safe hybrid comparison")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.data.open(encoding="utf-8")]
    chosen = selected_programmes(rows, args.split, args.programs)
    if not chosen:
        raise SystemExit("No programmes with text remain after split filtering")

    # Fit vocabulary/statistics on train only.  No test text is used to fit it.
    training_texts = []
    for row in rows:
        if row.get("split") != "train":
            continue
        training_texts.extend(course_text(course) for course in row.get("courses") or [])
        training_texts.extend(outcome_text(outcome) for outcome in row.get("outcomes") or [])
    vectorizer = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), min_df=2, max_features=80_000,
        sublinear_tf=True, norm="l2",
    )
    vectorizer.fit([value for value in training_texts if value])

    # A programme-level anchor is learned from train only.  It is useful for
    # recurring catalogue titles (e.g. the same course appears in several
    # universities) but never reads held-out programme edges.
    train_anchors: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row.get("split") != "train":
            continue
        courses = {str(course.get("id")): course for course in row.get("courses") or [] if course_text(course)}
        outcomes = {str(outcome.get("id")): outcome for outcome in row.get("outcomes") or [] if outcome_text(outcome)}
        edge_scores = {
            (str(edge.get("course_id")), str(edge.get("lo_id"))): float(edge.get("score") or 0.0)
            for edge in row.get("expert_edges") or []
            if edge.get("course_id") is not None and edge.get("lo_id") is not None
        }
        for edge in row.get("positive_edges") or []:
            if len(edge) < 2:
                continue
            course_id, lo_id = str(edge[0]), str(edge[1])
            if edge_scores.get((course_id, lo_id), 1.0) < args.min_expert_score:
                continue
            course = courses.get(course_id)
            outcome = outcomes.get(lo_id)
            key = title_key(course or {})
            if key and outcome:
                train_anchors[key].append(outcome_text(outcome))

    blocks: dict[str, dict] = {}
    for row in rows:
        program = str(row.get("program_id"))
        if program not in chosen:
            continue
        courses = {str(course.get("id")): course for course in row.get("courses") or [] if course_text(course)}
        outcomes = {str(outcome.get("id")): outcome for outcome in row.get("outcomes") or [] if outcome_text(outcome)}
        edge_scores = {
            (str(edge.get("course_id")), str(edge.get("lo_id"))): float(edge.get("score") or 0.0)
            for edge in row.get("expert_edges") or []
            if edge.get("course_id") is not None and edge.get("lo_id") is not None
        }
        links: dict[str, set[str]] = defaultdict(set)
        for edge in row.get("positive_edges") or []:
            if len(edge) < 2:
                continue
            course_id, lo_id = str(edge[0]), str(edge[1])
            if course_id in courses and lo_id in outcomes and edge_scores.get((course_id, lo_id), 1.0) >= args.min_expert_score:
                links[lo_id].add(course_id)
        course_ids = list(courses)
        lo_ids = [lo_id for lo_id in outcomes if links.get(lo_id)]
        if course_ids and lo_ids:
            blocks[program] = {
                "course_ids": course_ids,
                "lo_ids": lo_ids,
                "courses": [course_text(courses[course_id]) for course_id in course_ids],
                "course_keys": [title_key(courses[course_id]) for course_id in course_ids],
                "los": [outcome_text(outcomes[lo_id]) for lo_id in lo_ids],
                "links": links,
            }
    if not blocks:
        raise SystemExit("No benchmark queries remain after expert-score filtering")

    sbert_model = None
    if args.sbert_model:
        from sentence_transformers import SentenceTransformer
        sbert_model = SentenceTransformer(str(args.sbert_model), device=args.device)

    metrics = {"programmes": len(blocks), "queries": 0}
    values = defaultdict(list)
    total_queries = 0
    anchor_values = {weight: defaultdict(list) for weight in (0.25, 0.5, 0.75)}
    hybrid_values = {name: defaultdict(list) for name in ("sbert_0.5_lex_0.25_anchor_0.25", "sbert_0.6_lex_0.2_anchor_0.2", "sbert_0.25_lex_0.5_anchor_0.25")}
    for block in blocks.values():
        course_vectors = vectorizer.transform(block["courses"])
        lo_vectors = vectorizer.transform(block["los"])
        lexical_scores = (lo_vectors @ course_vectors.T).toarray()
        block_metrics = rank_metrics(block, lexical_scores)
        total_queries += int(block_metrics["queries"])
        for key, value in block_metrics.items():
            values[key].append(value)
        # Keep a second, leakage-safe variant: replace part of lexical score
        # with the best train-only LO anchor for an exactly recurring title.
        anchor_scores = np.zeros_like(lexical_scores)
        for course_index, key in enumerate(block["course_keys"]):
            anchors = train_anchors.get(key) or []
            if not anchors:
                continue
            anchor_matrix = vectorizer.transform(anchors)
            anchor_scores[:, course_index] = (
                lo_vectors @ anchor_matrix.T
            ).toarray().max(axis=1)
        for weight, aggregate in anchor_values.items():
            variant_metrics = rank_metrics(block, (1 - weight) * lexical_scores + weight * anchor_scores)
            for name, value in variant_metrics.items():
                if name != "queries":
                    aggregate[name].append(value * variant_metrics["queries"])
        if sbert_model is not None:
            sbert_course = sbert_model.encode(block["courses"], batch_size=48, normalize_embeddings=True, show_progress_bar=False)
            sbert_lo = sbert_model.encode(block["los"], batch_size=48, normalize_embeddings=True, show_progress_bar=False)
            sbert_scores = np.asarray(sbert_lo) @ np.asarray(sbert_course).T
            hybrid_scores = {
                "sbert_0.5_lex_0.25_anchor_0.25": 0.5 * sbert_scores + 0.25 * lexical_scores + 0.25 * anchor_scores,
                "sbert_0.6_lex_0.2_anchor_0.2": 0.6 * sbert_scores + 0.2 * lexical_scores + 0.2 * anchor_scores,
                "sbert_0.25_lex_0.5_anchor_0.25": 0.25 * sbert_scores + 0.5 * lexical_scores + 0.25 * anchor_scores,
            }
            for name, scores in hybrid_scores.items():
                variant_metrics = rank_metrics(block, scores)
                for metric, value in variant_metrics.items():
                    if metric != "queries":
                        hybrid_values[name][metric].append(value * variant_metrics["queries"])
    metrics["queries"] = total_queries
    for key, value in values.items():
        if key == "queries":
            continue
        # rank_metrics is averaged per programme; re-weight by query count so
        # programmes with many outcomes do not receive less statistical weight.
        weighted = []
        for block, block_value in zip(blocks.values(), value):
            weighted.append(block_value * len(block["lo_ids"]))
        metrics[key] = float(sum(weighted) / total_queries) if total_queries else 0.0
    for weight, aggregate in anchor_values.items():
        metrics[f"anchor_weight_{weight:g}"] = {
            name: float(sum(values) / total_queries) if total_queries else 0.0
            for name, values in aggregate.items()
        }
    for name, aggregate in hybrid_values.items():
        metrics[name] = {
            metric: float(sum(values) / total_queries) if total_queries else 0.0
            for metric, values in aggregate.items()
        }
    metrics["created_at"] = datetime.now(timezone.utc).isoformat()
    metrics["split"] = args.split
    metrics["candidate_pool_source"] = "programme_level"
    metrics["vectorizer_fit_split"] = "train"
    metrics["min_expert_score"] = args.min_expert_score
    metrics["sbert_model"] = str(args.sbert_model) if args.sbert_model else None
    metrics["device"] = args.device if args.sbert_model else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
