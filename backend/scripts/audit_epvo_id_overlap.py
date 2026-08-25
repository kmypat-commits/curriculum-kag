"""Audit train-to-held-out identity overlap for the EPVO ranking dataset.

This is a read-only, streaming diagnostic. It checks whether stable course/LO
identifiers can provide a leakage-safe prior before text reranking is changed.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def _text(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(str(value.get(key) or "").casefold() for key in ("ru", "kk", "kz", "en"))
    return str(value or "").casefold()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    train_pairs: set[tuple[str, str]] = set()
    train_course_los: dict[str, set[str]] = defaultdict(set)
    train_lo_courses: dict[str, set[str]] = defaultdict(set)
    train_titles: dict[str, set[str]] = defaultdict(set)
    heldout: dict[str, list[tuple[str, str, str]]] = defaultdict(list)

    with args.data.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            courses = {str(course.get("id")): course for course in row.get("courses") or []}
            outcomes = {str(outcome.get("id")): outcome for outcome in row.get("outcomes") or []}
            scores = {
                (str(edge.get("course_id")), str(edge.get("lo_id"))): float(edge.get("score") or 0.0)
                for edge in row.get("expert_edges") or []
                if edge.get("course_id") is not None and edge.get("lo_id") is not None
            }
            pairs = []
            for edge in row.get("positive_edges") or []:
                if len(edge) < 2:
                    continue
                course_id, lo_id = map(str, edge[:2])
                if (
                    course_id in courses
                    and lo_id in outcomes
                    and scores.get((course_id, lo_id), 1.0) >= 0.5
                ):
                    pairs.append((course_id, lo_id))
            if row.get("split") == "train":
                for course_id, lo_id in pairs:
                    train_pairs.add((course_id, lo_id))
                    train_course_los[course_id].add(lo_id)
                    train_lo_courses[lo_id].add(course_id)
                    title = _text(courses[course_id].get("title"))
                    if title:
                        train_titles[title].add(lo_id)
            elif row.get("split") in {"validation", "test"}:
                for course_id, lo_id in pairs:
                    heldout[str(row.get("split"))].append(
                        (course_id, lo_id, _text(courses[course_id].get("title")))
                    )

    for split, pairs in heldout.items():
        total = len(pairs) or 1
        exact = sum((course_id, lo_id) in train_pairs for course_id, lo_id, _ in pairs)
        course = sum(course_id in train_course_los for course_id, _, _ in pairs)
        lo = sum(lo_id in train_lo_courses for _, lo_id, _ in pairs)
        title = sum(title_key in train_titles for _, _, title_key in pairs)
        print(json.dumps({
            "split": split,
            "positive_pairs": len(pairs),
            "exact_course_lo_overlap": exact / total,
            "course_id_overlap": course / total,
            "lo_id_overlap": lo / total,
            "title_overlap": title / total,
        }, ensure_ascii=False))
    print(json.dumps({
        "train_pairs": len(train_pairs),
        "train_courses": len(train_course_los),
        "train_los": len(train_lo_courses),
        "train_titles": len(train_titles),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
