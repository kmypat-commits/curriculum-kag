"""Memory-bounded programme-level EPVO reranking benchmark.

The input JSONL can be larger than RAM.  The file is scanned twice: train text
statistics and expert anchors are accumulated in compact structures, while
only the selected held-out programmes are retained.  No held-out edges are
used for vectorizer statistics or anchor construction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.preprocessing import normalize

from benchmark_epvo_hybrid import course_text, outcome_text, rank_metrics, text_value, title_key


def localized_value(value: object, language: str) -> str:
    if isinstance(value, dict):
        aliases = (language, "kz") if language == "kk" else (language,)
        return next((str(value.get(key) or "").strip() for key in aliases if value.get(key)), "")
    return str(value or "").strip()


def localized_course_text(row: dict, language: str) -> str:
    return " | ".join(filter(None, (localized_value(row.get("title"), language), localized_value(row.get("description"), language))))


def localized_outcome_text(row: dict, language: str) -> str:
    return localized_value(row.get("text") or row.get("description") or row.get("title"), language)


class StreamingTfidf:
    def __init__(self, n_features: int = 2**17) -> None:
        self.vectorizer = HashingVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), n_features=n_features,
            alternate_sign=False, norm=None, binary=False, dtype=np.float32,
        )
        self.df = np.zeros(n_features, dtype=np.float32)
        self.documents = 0
        self.idf: np.ndarray | None = None

    def update(self, values: list[str], batch_size: int = 2048) -> None:
        values = [value for value in values if value]
        for start in range(0, len(values), batch_size):
            matrix = self.vectorizer.transform(values[start:start + batch_size])
            self.df += np.asarray((matrix > 0).sum(axis=0)).ravel()
            self.documents += matrix.shape[0]

    def finalize(self) -> None:
        self.idf = (np.log((1.0 + self.documents) / (1.0 + self.df)) + 1.0).astype(np.float32)

    def transform(self, values: list[str]):
        if self.idf is None:
            raise RuntimeError("StreamingTfidf.finalize() must run before transform")
        matrix = self.vectorizer.transform(values).multiply(self.idf)
        return normalize(matrix, norm="l2", axis=1, copy=False)


def selected_offsets(path: Path, split: str, limit: int) -> dict[str, int]:
    """Select deterministic held-out programmes and retain their byte offsets.

    The first pass still scans the source to apply the stable hash selection,
    but the later held-out pass seeks directly to these rows instead of
    rescanning the complete multi-gigabyte JSONL file.
    """
    candidates: list[tuple[str, str, int]] = []
    with path.open("rb") as stream:
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line:
                break
            row = json.loads(line)
            if row.get("split") != split:
                continue
            program_id = str(row.get("program_id"))
            candidates.append((
                hashlib.sha256(f"stream-v1:{split}:{program_id}".encode()).hexdigest(),
                program_id,
                offset,
            ))
    return {
        program_id: offset
        for _, program_id, offset in sorted(candidates)[:limit]
    }


def make_block(row: dict, threshold: float) -> dict | None:
    courses = {str(c.get("id")): c for c in row.get("courses") or [] if course_text(c)}
    outcomes = {str(o.get("id")): o for o in row.get("outcomes") or [] if outcome_text(o)}
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
        if course_id in courses and lo_id in outcomes and edge_scores.get((course_id, lo_id), 1.0) >= threshold:
            links[lo_id].add(course_id)
    lo_ids = [lo_id for lo_id in outcomes if links.get(lo_id)]
    if len(courses) < 2 or not lo_ids:
        return None
    course_ids = list(courses)
    return {
        "course_ids": course_ids,
        "lo_ids": lo_ids,
        "courses": [course_text(courses[cid]) for cid in course_ids],
        "course_titles": [text_value(courses[cid].get("title")) for cid in course_ids],
        "course_keys": [title_key(courses[cid]) for cid in course_ids],
        "los": [outcome_text(outcomes[lo_id]) for lo_id in lo_ids],
        "links": links,
        "course_langs": {
            language: [localized_course_text(courses[cid], language) for cid in course_ids]
            for language in ("ru", "kk", "en")
        },
        "lo_langs": {
            language: [localized_outcome_text(outcomes[lo_id], language) for lo_id in lo_ids]
            for language in ("ru", "kk", "en")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test"), default="validation")
    parser.add_argument("--programmes", type=int, default=80)
    parser.add_argument("--min-expert-score", type=float, default=0.5)
    parser.add_argument("--sbert-model", type=Path)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=48)
    parser.add_argument("--language", choices=("all", "ru", "kk", "en"), default="all")
    args = parser.parse_args()
    selected_offsets_by_programme = selected_offsets(args.data, args.split, args.programmes)
    selected = set(selected_offsets_by_programme)
    tfidf = StreamingTfidf()
    id_anchors: dict[str, list[str]] = defaultdict(list)
    title_anchors: dict[str, list[str]] = defaultdict(list)
    graded_id_anchors: dict[str, list[tuple[str, float]]] = defaultdict(list)
    graded_title_anchors: dict[str, list[tuple[str, float]]] = defaultdict(list)
    train_programmes = 0
    train_anchor_edges = 0

    for line in args.data.open(encoding="utf-8"):
        row = json.loads(line)
        if row.get("split") == "train":
            train_programmes += 1
            tfidf.update(
                [course_text(course) for course in row.get("courses") or []]
                + [outcome_text(outcome) for outcome in row.get("outcomes") or []]
            )
            courses = {str(c.get("id")): c for c in row.get("courses") or []}
            outcomes = {str(o.get("id")): o for o in row.get("outcomes") or []}
            scores = {
                (str(edge.get("course_id")), str(edge.get("lo_id"))): float(edge.get("score") or 0.0)
                for edge in row.get("expert_edges") or []
                if edge.get("course_id") is not None and edge.get("lo_id") is not None
            }
            for edge in row.get("positive_edges") or []:
                if len(edge) < 2:
                    continue
                course_id, lo_id = str(edge[0]), str(edge[1])
                if scores.get((course_id, lo_id), 1.0) < args.min_expert_score:
                    continue
                course = courses.get(course_id)
                outcome = outcomes.get(lo_id)
                if not course or not outcome:
                    continue
                lo = outcome_text(outcome)
                if not lo:
                    continue
                expert_score = scores.get((course_id, lo_id), 1.0)
                id_anchors[course_id].append(lo)
                title_anchors[title_key(course)].append(lo)
                graded_id_anchors[course_id].append((lo, expert_score))
                graded_title_anchors[title_key(course)].append((lo, expert_score))
                train_anchor_edges += 1
        # Held-out rows are deliberately processed only after train-only
        # statistics and anchors have been finalized below.  Keeping them out
        # of memory makes the benchmark genuinely streaming on the full
        # programme-level export.
    tfidf.finalize()
    sbert_model = None
    if args.sbert_model:
        from sentence_transformers import SentenceTransformer
        sbert_model = SentenceTransformer(str(args.sbert_model), device=args.device)
    # Bound repeated catalogue anchors without changing the train-only rule.
    id_anchors = {key: list(dict.fromkeys(values))[:128] for key, values in id_anchors.items()}
    title_anchors = {key: list(dict.fromkeys(values))[:128] for key, values in title_anchors.items()}

    def bound_graded(values: list[tuple[str, float]]) -> list[tuple[str, float]]:
        strongest: dict[str, float] = {}
        for text, score in values:
            strongest[text] = max(strongest.get(text, 0.0), float(score))
        return list(strongest.items())[:128]

    graded_id_anchors = {key: bound_graded(values) for key, values in graded_id_anchors.items()}
    graded_title_anchors = {key: bound_graded(values) for key, values in graded_title_anchors.items()}

    totals = defaultdict(float)
    query_count = 0
    variants = (0.15, 0.25, 0.35, 0.50)
    variant_totals = {weight: defaultdict(float) for weight in variants}
    graded_anchor_totals = defaultdict(float)
    hybrid_totals = {
        "sbert_0.5_lex_0.25_anchor_0.25": defaultdict(float),
        "sbert_0.6_lex_0.2_anchor_0.2": defaultdict(float),
        "sbert_0.25_lex_0.25_anchor_0.5": defaultdict(float),
    }
    processed_programmes = 0
    # Seek directly to the selected held-out rows after fitting train-only
    # statistics.  Only one held-out programme is materialized at a time; no
    # test text or expert edge enters the vectorizer/anchor state.
    with args.data.open("rb") as heldout_stream:
        for program_id, offset in sorted(
            selected_offsets_by_programme.items(), key=lambda item: item[1]
        ):
            heldout_stream.seek(offset)
            row = json.loads(heldout_stream.readline())
            if row.get("split") != args.split or str(row.get("program_id")) != program_id:
                raise RuntimeError(
                    f"Selected programme offset drifted: expected {program_id}"
                )
            block = make_block(row, args.min_expert_score)
            if block is None:
                continue
            processed_programmes += 1
            course_vectors = tfidf.transform(block["courses"])
            lo_vectors = tfidf.transform(block["los"])
            lexical = (lo_vectors @ course_vectors.T).toarray()
            base = rank_metrics(block, lexical)
            query_count += base["queries"]
            for metric in ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10"):
                totals[metric] += base[metric] * base["queries"]
            anchor = np.zeros_like(lexical)
            graded_anchor = np.zeros_like(lexical)
            for course_index, course_id in enumerate(block["course_ids"]):
                values = id_anchors.get(course_id, []) + title_anchors.get(block["course_keys"][course_index], [])
                if values:
                    anchor[:, course_index] = (lo_vectors @ tfidf.transform(list(dict.fromkeys(values))).T).toarray().max(axis=1)
                weighted_values = graded_id_anchors.get(course_id, []) + graded_title_anchors.get(block["course_keys"][course_index], [])
                if weighted_values:
                    weighted_texts = [text for text, _ in weighted_values]
                    weighted_strengths = np.asarray([0.5 + 0.5 * score for _, score in weighted_values])
                    similarities = (lo_vectors @ tfidf.transform(weighted_texts).T).toarray()
                    graded_anchor[:, course_index] = (similarities * weighted_strengths).max(axis=1)
            for weight in variants:
                result = rank_metrics(block, (1.0 - weight) * lexical + weight * anchor)
                for metric in ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10"):
                    variant_totals[weight][metric] += result[metric] * result["queries"]
            graded_result = rank_metrics(block, 0.65 * lexical + 0.35 * graded_anchor)
            graded_anchor_totals["queries"] += graded_result["queries"]
            for metric in ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10"):
                graded_anchor_totals[metric] += graded_result[metric] * graded_result["queries"]
            if sbert_model is not None:
                sbert_courses = sbert_model.encode(
                    block["courses"] if args.language == "all" else block["course_langs"][args.language], batch_size=args.batch_size,
                    normalize_embeddings=True, show_progress_bar=False,
                )
                sbert_los = sbert_model.encode(
                    block["los"] if args.language == "all" else block["lo_langs"][args.language], batch_size=args.batch_size,
                    normalize_embeddings=True, show_progress_bar=False,
                )
                sbert_scores = np.asarray(sbert_los) @ np.asarray(sbert_courses).T
                hybrid_scores = {
                    "sbert_0.5_lex_0.25_anchor_0.25": 0.50 * sbert_scores + 0.25 * lexical + 0.25 * anchor,
                    "sbert_0.6_lex_0.2_anchor_0.2": 0.60 * sbert_scores + 0.20 * lexical + 0.20 * anchor,
                    "sbert_0.25_lex_0.25_anchor_0.5": 0.25 * sbert_scores + 0.25 * lexical + 0.50 * anchor,
                }
                for name, scores in hybrid_scores.items():
                    result = rank_metrics(block, scores)
                    for metric in ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10"):
                        hybrid_totals[name][metric] += result[metric] * result["queries"]

    output = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "split": args.split,
        "programmes": processed_programmes,
        "queries": query_count,
        "train_programmes": train_programmes,
        "train_documents": tfidf.documents,
        "train_anchor_edges": train_anchor_edges,
        "vectorizer": "train-only streaming HashingTFIDF char_wb",
        "min_expert_score": args.min_expert_score,
        "sbert_model": str(args.sbert_model) if args.sbert_model else None,
        "device": args.device if args.sbert_model else None,
        "language": args.language,
    }
    for metric in ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10"):
        output[metric] = totals[metric] / query_count if query_count else 0.0
    for weight, values in variant_totals.items():
        output[f"anchor_weight_{weight:g}"] = {
            metric: values[metric] / query_count if query_count else 0.0
            for metric in ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10")
        }
    output["graded_anchor_weight_0.35"] = {
        metric: graded_anchor_totals[metric] / query_count if query_count else 0.0
        for metric in ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10")
    }
    for name, values in hybrid_totals.items():
        output[name] = {
            metric: values[metric] / query_count if query_count else 0.0
            for metric in ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10")
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
