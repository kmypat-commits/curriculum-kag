"""Audit the frozen EPVO ranking split and compute the attainable Recall@K ceiling."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "experiment-results" / "epvo-link-context-dataset" / "programs.jsonl"


def localized(value: dict) -> str:
    return str(value.get("ru") or value.get("kz") or value.get("en") or "").strip()


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def digest(value: str) -> str:
    return hashlib.sha1(normalized(value).encode("utf-8")).hexdigest()


def percentile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summary(values: list[int]) -> dict:
    return {
        "count": len(values),
        "min": min(values) if values else 0,
        "p50": percentile(values, 0.5),
        "p90": percentile(values, 0.9),
        "p95": percentile(values, 0.95),
        "max": max(values) if values else 0,
        "mean": sum(values) / len(values) if values else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--output", default=str(ROOT / "experiment-results" / "epvo-ranking-audit" / "audit.json"))
    parser.add_argument("--programs", type=int, default=120)
    parser.add_argument("--seed-prefix", default="ranking-v1")
    args = parser.parse_args()

    ids_by_split: dict[str, set[str]] = defaultdict(set)
    course_hash_splits: dict[str, set[str]] = defaultdict(set)
    lo_hash_splits: dict[str, set[str]] = defaultdict(set)
    test_rows: list[tuple[str, dict]] = []
    malformed_edges = 0
    with Path(args.data).open(encoding="utf-8") as source:
        for line in source:
            program = json.loads(line)
            split = str(program.get("split") or "unknown")
            program_id = str(program.get("program_id"))
            ids_by_split[split].add(program_id)
            courses = {str(item["id"]): item for item in program.get("courses") or []}
            outcomes = {str(item["id"]): item for item in program.get("outcomes") or []}
            for course in courses.values():
                text = " | ".join(filter(None, (localized(course.get("title") or {}), localized(course.get("description") or {}))))
                if text:
                    course_hash_splits[digest(text)].add(split)
            for outcome in outcomes.values():
                text = localized(outcome.get("text") or {})
                if text:
                    lo_hash_splits[digest(text)].add(split)
            for course_id, lo_id in program.get("positive_edges") or []:
                malformed_edges += int(str(course_id) not in courses or str(lo_id) not in outcomes)
            if split == "test":
                rank = hashlib.sha256(f"{args.seed_prefix}:test:{program_id}".encode()).hexdigest()
                test_rows.append((rank, program))

    selected = [program for _, program in sorted(test_rows)[: args.programs]]
    candidate_counts: list[int] = []
    relevant_counts: list[int] = []
    oracle_recall_5: list[float] = []
    oracle_recall_10: list[float] = []
    queries_over_10 = 0
    duplicated_course_texts = 0
    for program in selected:
        courses = {str(item["id"]): item for item in program.get("courses") or []}
        links: dict[str, set[str]] = defaultdict(set)
        for course_id, lo_id in program.get("positive_edges") or []:
            if str(course_id) in courses:
                links[str(lo_id)].add(str(course_id))
        hashes = [digest(" | ".join(filter(None, (localized(item.get("title") or {}), localized(item.get("description") or {}))))) for item in courses.values()]
        duplicated_course_texts += sum(count - 1 for count in Counter(hashes).values() if count > 1)
        candidate_counts.extend([len(courses)] * len(links))
        for relevant in links.values():
            count = len(relevant)
            relevant_counts.append(count)
            queries_over_10 += int(count > 10)
            oracle_recall_5.append(min(5, count) / count)
            oracle_recall_10.append(min(10, count) / count)

    split_overlap = {}
    split_names = sorted(ids_by_split)
    for index, left in enumerate(split_names):
        for right in split_names[index + 1 :]:
            split_overlap[f"{left}:{right}"] = len(ids_by_split[left] & ids_by_split[right])
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": str(Path(args.data).resolve()),
        "seed_policy": f"sha256({args.seed_prefix}:test:program_id)",
        "programme_counts": {key: len(value) for key, value in ids_by_split.items()},
        "programme_id_overlap": split_overlap,
        "exact_course_text_hashes_across_splits": sum(len(splits) > 1 for splits in course_hash_splits.values()),
        "exact_lo_text_hashes_across_splits": sum(len(splits) > 1 for splits in lo_hash_splits.values()),
        "malformed_positive_edges": malformed_edges,
        "selected_test_programmes": len(selected),
        "queries": len(relevant_counts),
        "candidate_courses_per_query": summary(candidate_counts),
        "relevant_courses_per_query": summary(relevant_counts),
        "queries_with_more_than_10_relevant": queries_over_10,
        "oracle_recall_at_5": sum(oracle_recall_5) / len(oracle_recall_5),
        "oracle_recall_at_10": sum(oracle_recall_10) / len(oracle_recall_10),
        "duplicate_course_text_rows_inside_selected_programmes": duplicated_course_texts,
        "target_recall_at_10_0_90_is_mathematically_reachable": (sum(oracle_recall_10) / len(oracle_recall_10)) >= 0.90,
        "notes": [
            "Programme IDs must be disjoint across train/validation/test.",
            "Exact course/LO text can legitimately recur across different programmes; it is reported as a memorisation risk, not programme leakage.",
            "Oracle Recall@K is limited when one LO has more than K declared relevant courses.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
