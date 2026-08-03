"""Export numeric expert feedback for a leakage-safe reranking experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, text


def split_for(version_id: int) -> str:
    bucket = int(hashlib.sha256(f"feedback-v1:{version_id}".encode()).hexdigest()[:8], 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--output", type=Path, default=Path(".runtime/expert-feedback-dataset"))
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")
    engine = create_engine(args.database_url, pool_pre_ping=True)
    args.output.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    score_values: set[float] = set()
    rows = 0
    with engine.connect() as db, (args.output / "feedback.jsonl").open("w", encoding="utf-8") as stream:
        result = db.execute(text(
            "SELECT f.id, f.project_version_id, f.course_id, f.lo_id, f.verdict, "
            "f.corrected_score, f.comment, f.created_at, c.title AS course_title, "
            "c.description AS course_description, l.lo_code, l.lo_text "
            "FROM match_feedback f JOIN courses c ON c.id=f.course_id "
            "JOIN learning_outcomes l ON l.id=f.lo_id "
            "WHERE f.corrected_score IS NOT NULL ORDER BY f.id"
        )).mappings()
        for row in result:
            score = float(row["corrected_score"])
            if not 0.0 <= score <= 1.0:
                continue
            split = split_for(int(row["project_version_id"]))
            item = {
                "feedback_id": row["id"],
                "project_version_id": row["project_version_id"],
                "course_id": row["course_id"],
                "lo_id": row["lo_id"],
                "course_title": row["course_title"],
                "course_description": row["course_description"],
                "lo_code": row["lo_code"],
                "lo_text": row["lo_text"],
                "verdict": row["verdict"],
                "corrected_score": score,
                "comment": row["comment"],
                "split": split,
            }
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
            rows += 1
            counts[split] += 1
            score_values.add(score)
    manifest = {
        "source": "match_feedback.corrected_score",
        "rows": rows,
        "split_counts": dict(counts),
        "programme_version_level_split": True,
        "unique_scores": sorted(score_values),
        "status": "ready" if rows and len(score_values) >= 2 else "insufficient_score_diversity",
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
