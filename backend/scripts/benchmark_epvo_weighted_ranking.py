"""Frozen retrieval benchmark using EPVO expert strength as graded relevance."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer


def text(value: dict) -> str:
    return value.get("ru") or value.get("kz") or value.get("en") or ""


def metrics(data: dict[str, dict], model: SentenceTransformer, programmes: int) -> dict:
    recall5: list[float] = []
    recall10: list[float] = []
    reciprocal: list[float] = []
    ndcg10: list[float] = []
    weighted_ndcg10: list[float] = []
    selected = sorted(data, key=lambda p: hashlib.sha256(f"weighted-ranking:test:{p}".encode()).hexdigest())[:programmes]
    for program in selected:
        block = data[program]
        course_ids = list(block["courses"])
        lo_ids = [lo for lo in block["los"] if block["relevance"].get(lo)]
        if len(course_ids) < 2 or not lo_ids:
            continue
        cv = model.encode([block["courses"][x] for x in course_ids], batch_size=48, normalize_embeddings=True, show_progress_bar=False)
        lv = model.encode([block["los"][x] for x in lo_ids], batch_size=48, normalize_embeddings=True, show_progress_bar=False)
        scores = np.asarray(lv) @ np.asarray(cv).T
        for i, lo_id in enumerate(lo_ids):
            relevance = block["relevance"][lo_id]
            graded = {cid: value for cid, value in relevance.items() if value >= 0.5}
            if not graded:
                continue
            ranking = [course_ids[j] for j in np.argsort(-scores[i])]
            recall5.append(sum(cid in graded for cid in ranking[:5]) / len(graded))
            recall10.append(sum(cid in graded for cid in ranking[:10]) / len(graded))
            first = next((pos + 1 for pos, cid in enumerate(ranking) if cid in graded), None)
            reciprocal.append(1 / first if first else 0.0)
            dcg = sum((1.0 if cid in graded else 0.0) / math.log2(pos + 2) for pos, cid in enumerate(ranking[:10]))
            ideal = sum(1.0 / math.log2(pos + 2) for pos in range(min(len(graded), 10)))
            ndcg10.append(dcg / ideal if ideal else 0.0)
            gains = [graded.get(cid, 0.0) for cid in ranking[:10]]
            gdcg = sum(gain / math.log2(pos + 2) for pos, gain in enumerate(gains))
            ideal_gains = sorted(graded.values(), reverse=True)[:10]
            ideal_gdcg = sum(gain / math.log2(pos + 2) for pos, gain in enumerate(ideal_gains))
            weighted_ndcg10.append(gdcg / ideal_gdcg if ideal_gdcg else 0.0)
    return {"programmes": len(selected), "queries": len(recall10), "recall_at_5": float(np.mean(recall5)), "recall_at_10": float(np.mean(recall10)), "mrr": float(np.mean(reciprocal)), "ndcg_at_10": float(np.mean(ndcg10)), "graded_ndcg_at_10": float(np.mean(weighted_ndcg10))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=".runtime/epvo-weighted-postgres/course_lo_pairs.jsonl")
    ap.add_argument("--model", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--programmes", type=int, default=80)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()
    data = defaultdict(lambda: {"courses": {}, "los": {}, "relevance": defaultdict(dict)})
    with Path(args.data).open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("split") != "test" or row.get("expert_score") is None:
                continue
            p = str(row["program_id"]); c = str(row["course_id"]); lo = str(row["lo_id"])
            data[p]["courses"][c] = text(row.get("course_title") or {}) + ". " + text(row.get("course_description") or {})
            data[p]["los"][lo] = text(row.get("lo_text") or {})
            data[p]["relevance"][lo][c] = float(row["expert_score"])
    model = SentenceTransformer(args.model, device=args.device, local_files_only=True)
    result = {"data": args.data, "model": args.model, "split": "test", "relevance": "expert_score >= 0.5; graded nDCG uses 0.5..1.0", "metrics": metrics(data, model, args.programmes)}
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
