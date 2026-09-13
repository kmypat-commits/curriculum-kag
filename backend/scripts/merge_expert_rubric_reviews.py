"""Merge two independently completed blinded review packets for scoring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _review_map(payload: dict[str, Any], reviewer: str) -> dict[str, dict[str, Any]]:
    if payload.get("format") != "curriculum-kag.blind-expert-review.v1":
        raise ValueError("Unsupported review packet format")
    if payload.get("reviewer") != reviewer:
        raise ValueError(f"Expected a {reviewer} packet")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Review packet has no items")
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Review item must be an object")
        anonymous_id = str(item.get("anonymous_plan_id") or "").strip()
        assessment = item.get("assessment")
        if not anonymous_id or not isinstance(assessment, dict) or anonymous_id in result:
            raise ValueError("Review packet has invalid or duplicate anonymous IDs")
        result[anonymous_id] = assessment
    return result


def merge_reviews(expert_a: dict[str, Any], expert_b: dict[str, Any]) -> dict[str, Any]:
    left, right = _review_map(expert_a, "expert-a"), _review_map(expert_b, "expert-b")
    if set(left) != set(right):
        raise ValueError("Expert packets must contain the identical anonymous plan IDs")
    items = []
    for anonymous_id in sorted(left):
        a, b = left[anonymous_id], right[anonymous_id]
        item = {
            "anonymous_plan_id": anonymous_id,
            "expert_a": {key: a.get(key) for key in ("relevance", "semester", "bridge")},
            "expert_b": {key: b.get(key) for key in ("relevance", "semester", "bridge")},
            "software_validity": {"expert_a": a.get("software_validity"), "expert_b": b.get("software_validity")},
            "content_validity": {"expert_a": a.get("content_validity"), "expert_b": b.get("content_validity")},
        }
        items.append(item)
    return {"items": items}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("expert_a", type=Path)
    parser.add_argument("expert_b", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    merged = merge_reviews(
        json.loads(args.expert_a.read_text(encoding="utf-8")),
        json.loads(args.expert_b.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Merged {len(merged['items'])} independent expert reviews into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
