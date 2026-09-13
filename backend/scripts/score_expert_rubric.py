"""Score a blinded two-expert curriculum review and report agreement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DIMENSIONS = ("relevance", "semester", "bridge")


def _kappa(left: list[int], right: list[int]) -> float | None:
    if not left or len(left) != len(right):
        return None
    observed = sum(a == b for a, b in zip(left, right)) / len(left)
    categories = sorted(set(left) | set(right))
    expected = sum(
        (left.count(category) / len(left)) * (right.count(category) / len(right))
        for category in categories
    )
    if expected == 1:
        return 1.0
    return round((observed - expected) / (1 - expected), 4)


def score_review(payload: dict) -> dict:
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("Review must contain a non-empty items list")
    anonymous_ids = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get("anonymous_plan_id") or "").strip():
            raise ValueError("Every item must contain a non-empty anonymous_plan_id")
        anonymous_ids.append(str(item["anonymous_plan_id"]).strip())
    if len(set(anonymous_ids)) != len(anonymous_ids):
        raise ValueError("anonymous_plan_id values must be unique")
    result = {"items": len(items), "dimensions": {}, "software_validity": {}, "content_validity": {}}
    for dimension in DIMENSIONS:
        expert_a, expert_b = [], []
        for item in items:
            a = ((item.get("expert_a") or {}).get(dimension))
            b = ((item.get("expert_b") or {}).get(dimension))
            if not isinstance(a, int) or not isinstance(b, int) or not 1 <= a <= 5 or not 1 <= b <= 5:
                raise ValueError(f"Each {dimension} rating must be an integer from 1 to 5")
            expert_a.append(a)
            expert_b.append(b)
        result["dimensions"][dimension] = {
            "expert_a_mean": round(sum(expert_a) / len(expert_a), 3),
            "expert_b_mean": round(sum(expert_b) / len(expert_b), 3),
            "exact_agreement": round(sum(a == b for a, b in zip(expert_a, expert_b)) / len(expert_a), 3),
            "cohens_kappa": _kappa(expert_a, expert_b),
        }
    for key in ("software_validity", "content_validity"):
        values = [item.get(key) for item in items]
        if not all(isinstance(value, dict) for value in values):
            raise ValueError(f"Every item must contain both expert {key} assessments")
        for value in values:
            if not all(isinstance(value.get(expert), bool) for expert in ("expert_a", "expert_b")):
                raise ValueError(f"Every {key} assessment must contain boolean expert_a and expert_b values")
        expert_a = [int(value["expert_a"]) for value in values]
        expert_b = [int(value["expert_b"]) for value in values]
        result[key] = {
            "expert_a_pass_rate": round(sum(expert_a) / len(expert_a), 3),
            "expert_b_pass_rate": round(sum(expert_b) / len(expert_b), 3),
            "exact_agreement": round(sum(a == b for a, b in zip(expert_a, expert_b)) / len(expert_a), 3),
            "cohens_kappa": _kappa(expert_a, expert_b),
        }
    result["interpretation"] = "Software validity and content validity are reported separately; this is not accreditation evidence."
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = score_review(json.loads(args.input.read_text(encoding="utf-8")))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
