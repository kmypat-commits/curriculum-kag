"""Leakage-safe supervised pair reranking experiment for EPVO.

This is an experiment only.  It learns a small pair classifier from complete
training programmes and evaluates ranking on held-out programmes.  No test
programme edges are used to build features or fit the classifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def text_value(value: object) -> str:
    if isinstance(value, dict):
        return " | ".join(str(value.get(key) or "").strip() for key in ("ru", "kz", "kk", "en") if value.get(key))
    return str(value or "").strip()


def course_text(row: dict) -> str:
    return " | ".join(filter(None, (text_value(row.get("title")), text_value(row.get("description")))))


def outcome_text(row: dict) -> str:
    return text_value(row.get("text") or row.get("description") or row.get("title"))


def title_key(row: dict) -> str:
    return " ".join(TOKEN_RE.findall(text_value(row.get("title")).casefold()))


def token_set(value: str) -> set[str]:
    return set(TOKEN_RE.findall(value.casefold()))


def chosen(rows: list[dict], split: str, limit: int) -> set[str]:
    values = []
    for row in rows:
        if row.get("split") != split:
            continue
        if not row.get("courses") or not row.get("outcomes"):
            continue
        key = str(row.get("program_id"))
        values.append((hashlib.sha256(f"supervised-v1:{split}:{key}".encode()).hexdigest(), key))
    return {key for _, key in sorted(values)[:limit]}


def metrics(block: dict, scores: np.ndarray) -> dict[str, float]:
    recalls = []
    mrr = []
    ndcgs = []
    for i, lo_id in enumerate(block["lo_ids"]):
        relevant = block["links"].get(lo_id, set())
        if not relevant:
            continue
        ranking = [block["course_ids"][j] for j in np.argsort(-scores[i])]
        recalls.append(sum(x in relevant for x in ranking[:10]) / len(relevant))
        first = next((j + 1 for j, x in enumerate(ranking) if x in relevant), None)
        mrr.append(1.0 / first if first else 0.0)
        dcg = sum((1.0 if x in relevant else 0.0) / math.log2(j + 2) for j, x in enumerate(ranking[:10]))
        ideal = sum(1.0 / math.log2(j + 2) for j in range(min(len(relevant), 10)))
        ndcgs.append(dcg / ideal if ideal else 0.0)
    if not recalls:
        return {"queries": 0, "recall_at_10": 0.0, "mrr": 0.0, "ndcg_at_10": 0.0}
    return {"queries": len(recalls), "recall_at_10": float(np.mean(recalls)), "mrr": float(np.mean(mrr)), "ndcg_at_10": float(np.mean(ndcgs))}


def build_blocks(rows: list[dict], split: str, programme_ids: set[str], threshold: float) -> dict[str, dict]:
    blocks = {}
    for row in rows:
        pid = str(row.get("program_id"))
        if row.get("split") != split or pid not in programme_ids:
            continue
        courses = {str(c.get("id")): c for c in row.get("courses") or [] if course_text(c)}
        outcomes = {str(o.get("id")): o for o in row.get("outcomes") or [] if outcome_text(o)}
        edge_scores = {(str(e.get("course_id")), str(e.get("lo_id"))): float(e.get("score") or 0.0) for e in row.get("expert_edges") or []}
        links: dict[str, set[str]] = defaultdict(set)
        for edge in row.get("positive_edges") or []:
            if len(edge) < 2:
                continue
            c, lo = str(edge[0]), str(edge[1])
            if c in courses and lo in outcomes and edge_scores.get((c, lo), 1.0) >= threshold:
                links[lo].add(c)
        lo_ids = [lo for lo in outcomes if links.get(lo)]
        if courses and lo_ids:
            blocks[pid] = {
                "course_ids": list(courses),
                "lo_ids": lo_ids,
                "courses": [course_text(courses[c]) for c in courses],
                "course_titles": [text_value(courses[c].get("title")) for c in courses],
                "course_keys": [title_key(courses[c]) for c in courses],
                "los": [outcome_text(outcomes[lo]) for lo in lo_ids],
                "links": links,
            }
    return blocks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test"), default="validation")
    parser.add_argument("--programmes", type=int, default=80)
    parser.add_argument("--train-programmes", type=int, default=300)
    parser.add_argument("--min-expert-score", type=float, default=0.5)
    parser.add_argument("--negatives-per-positive", type=int, default=4)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.data.open(encoding="utf-8")]
    train_ids = chosen(rows, "train", args.train_programmes)
    train_rows = [row for row in rows if row.get("split") == "train" and str(row.get("program_id")) in train_ids]
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, max_features=40000, sublinear_tf=True)
    word_vectorizer = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, max_features=30000, sublinear_tf=True)
    fit_text = [course_text(c) for r in train_rows for c in r.get("courses") or []] + [outcome_text(o) for r in train_rows for o in r.get("outcomes") or []]
    fit_text = [x for x in fit_text if x]
    vectorizer.fit(fit_text)
    word_vectorizer.fit(fit_text)

    # Train-only recurring course/title anchors.  IDs are catalogue IDs, not
    # programme IDs; their use is therefore leakage-safe for held-out programmes.
    id_los: dict[str, list[str]] = defaultdict(list)
    title_los: dict[str, list[str]] = defaultdict(list)
    for row in train_rows:
        courses = {str(c.get("id")): c for c in row.get("courses") or []}
        outcomes = {str(o.get("id")): o for o in row.get("outcomes") or []}
        scores = {(str(e.get("course_id")), str(e.get("lo_id"))): float(e.get("score") or 0.0) for e in row.get("expert_edges") or []}
        for edge in row.get("positive_edges") or []:
            if len(edge) < 2:
                continue
            cid, oid = str(edge[0]), str(edge[1])
            if scores.get((cid, oid), 1.0) < args.min_expert_score or cid not in courses or oid not in outcomes:
                continue
            lo = outcome_text(outcomes[oid])
            if lo:
                id_los[cid].append(lo)
                if title_key(courses[cid]):
                    title_los[title_key(courses[cid])].append(lo)
    id_los = {key: list(dict.fromkeys(value)) for key, value in id_los.items()}
    title_los = {key: list(dict.fromkeys(value)) for key, value in title_los.items()}

    # Build train-only pair features. Anchor text is derived only from the
    # training programmes, so held-out programme edges never enter features.
    def features(course_values: list[str], title_values: list[str], lo_values: list[str], ids: list[str]) -> np.ndarray:
        chars_c = vectorizer.transform(course_values)
        chars_l = vectorizer.transform(lo_values)
        words_c = word_vectorizer.transform(course_values)
        words_l = word_vectorizer.transform(lo_values)
        char_score = (chars_l @ chars_c.T).toarray()
        word_score = (words_l @ words_c.T).toarray()
        result = np.zeros((len(lo_values), len(course_values), 7), dtype=np.float32)
        result[:, :, 0] = char_score
        result[:, :, 1] = word_score
        lo_tokens = [token_set(value) for value in lo_values]
        course_tokens = [token_set(value) for value in course_values]
        for li, left in enumerate(lo_tokens):
            for ci, right in enumerate(course_tokens):
                result[li, ci, 2] = len(left & right) / max(1, len(left | right))
        for ci, cid in enumerate(ids):
            anchors = id_los.get(cid, [])
            title_anchors = title_los.get(title_key({"title": title_values[ci]}), [])
            if anchors:
                result[:, ci, 3] = (chars_l @ vectorizer.transform(anchors).T).toarray().max(axis=1)
            if title_anchors:
                result[:, ci, 4] = (chars_l @ vectorizer.transform(title_anchors).T).toarray().max(axis=1)
            result[:, ci, 5] = 1.0 if anchors else 0.0
            result[:, ci, 6] = min(len(course_tokens[ci]), 80) / 80.0
        return result

    rng = np.random.default_rng(20260825)
    train_x = []
    train_y = []
    for row in train_rows:
        courses = {str(c.get("id")): c for c in row.get("courses") or [] if course_text(c)}
        outcomes = {str(o.get("id")): o for o in row.get("outcomes") or [] if outcome_text(o)}
        positives = set()
        scores = {(str(e.get("course_id")), str(e.get("lo_id"))): float(e.get("score") or 0.0) for e in row.get("expert_edges") or []}
        for edge in row.get("positive_edges") or []:
            if len(edge) >= 2 and scores.get((str(edge[0]), str(edge[1])), 1.0) >= args.min_expert_score:
                positives.add((str(edge[0]), str(edge[1])))
        if not positives:
            continue
        course_ids = list(courses)
        lo_ids = list(outcomes)
        f = features([course_text(courses[c]) for c in course_ids], [text_value(courses[c].get("title")) for c in course_ids], [outcome_text(outcomes[o]) for o in lo_ids], course_ids)
        for li, oid in enumerate(lo_ids):
            pos = [ci for ci, cid in enumerate(course_ids) if (cid, oid) in positives]
            if not pos:
                continue
            neg = [ci for ci, cid in enumerate(course_ids) if (cid, oid) not in positives]
            if len(neg) > args.negatives_per_positive * len(pos):
                neg = list(rng.choice(neg, size=args.negatives_per_positive * len(pos), replace=False))
            train_x.extend(f[li, pos].tolist())
            train_y.extend([1] * len(pos))
            train_x.extend(f[li, neg].tolist())
            train_y.extend([0] * len(neg))
    scaler = StandardScaler()
    X = scaler.fit_transform(np.asarray(train_x, dtype=np.float32))
    clf = LogisticRegression(max_iter=300, class_weight="balanced", C=1.0, random_state=20260825)
    clf.fit(X, train_y)
    blocks = build_blocks(rows, args.split, chosen(rows, args.split, args.programmes), args.min_expert_score)
    sums = defaultdict(float)
    queries = 0
    for block in blocks.values():
        f = features(block["courses"], block["course_titles"], block["los"], block["course_ids"])
        scores = clf.predict_proba(scaler.transform(f.reshape(-1, f.shape[-1])))[:, 1].reshape(f.shape[:2])
        result = metrics(block, scores)
        queries += result["queries"]
        for key in ("recall_at_10", "mrr", "ndcg_at_10"):
            sums[key] += result[key] * result["queries"]
    output = {"split": args.split, "programmes": len(blocks), "queries": queries, **{key: sums[key] / queries if queries else 0.0 for key in ("recall_at_10", "mrr", "ndcg_at_10")}, "train_programmes": len(train_rows), "train_pairs": len(train_y), "min_expert_score": args.min_expert_score}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
