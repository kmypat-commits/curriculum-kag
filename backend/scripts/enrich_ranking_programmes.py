"""Repair a programme-level ranking export with graded EPVO edge evidence.

This is useful when an older export contains complete programme/course text but
was produced before ``expert_edges`` was added.  It joins the immutable
positive-pair file by ``(program_id, course_id, lo_id)`` and writes new JSONL
artifacts without modifying the source files.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--programmes", type=Path, required=True)
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--output-programmes", type=Path, required=True)
    parser.add_argument("--output-pairs", type=Path, required=True)
    args = parser.parse_args()

    programme_rows: list[dict] = []
    programme_text: dict[str, dict[str, dict[str, dict]]] = {}
    with args.programmes.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            program_id = str(row.get("program_id"))
            programme_rows.append(row)
            programme_text[program_id] = {
                "courses": {
                    str(course.get("id") or course.get("course_id")): course
                    for course in row.get("courses") or []
                },
                "outcomes": {
                    str(outcome.get("id") or outcome.get("lo_id")): outcome
                    for outcome in row.get("outcomes") or []
                },
            }

    scores: dict[str, dict[tuple[str, str], float]] = defaultdict(dict)
    pair_rows: list[dict] = []
    with args.pairs.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            pair_rows.append(row)
            key = (str(row.get("course_id")), str(row.get("lo_id")))
            score = float(row.get("expert_score")) if row.get("expert_score") is not None else 1.0
            program_id = str(row.get("program_id"))
            scores[program_id][key] = max(score, scores[program_id].get(key, 0.0))

    args.output_programmes.parent.mkdir(parents=True, exist_ok=True)
    args.output_pairs.parent.mkdir(parents=True, exist_ok=True)
    edge_count = 0
    with args.output_programmes.open("w", encoding="utf-8") as stream:
        for row in programme_rows:
            program_id = str(row.get("program_id"))
            existing = {
                (str(edge.get("course_id")), str(edge.get("lo_id"))): float(edge.get("score") or 0.0)
                for edge in row.get("expert_edges") or []
                if edge.get("course_id") is not None and edge.get("lo_id") is not None
            }
            existing.update(scores.get(program_id, {}))
            row["expert_edges"] = [
                {"course_id": course_id, "lo_id": lo_id, "score": score}
                for (course_id, lo_id), score in sorted(existing.items())
            ]
            edge_count += len(row["expert_edges"])
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    enriched_pairs = 0
    with args.output_pairs.open("w", encoding="utf-8") as stream:
        for row in pair_rows:
            context = programme_text.get(str(row.get("program_id")), {})
            course = (context.get("courses") or {}).get(str(row.get("course_id")), {})
            outcome = (context.get("outcomes") or {}).get(str(row.get("lo_id")), {})
            row["course_title"] = course.get("title") or {}
            row["course_description"] = course.get("description") or {}
            row["lo_text"] = outcome.get("text") or outcome.get("description") or {}
            enriched_pairs += int(bool(row["course_title"] or row["course_description"] or row["lo_text"]))
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps({
        "programmes": len(programme_rows),
        "expert_edges": edge_count,
        "pairs": len(pair_rows),
        "pairs_with_text": enriched_pairs,
        "output_programmes": str(args.output_programmes),
        "output_pairs": str(args.output_pairs),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
