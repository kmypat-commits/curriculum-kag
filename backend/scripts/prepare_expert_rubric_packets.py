"""Create two anonymous, independent curriculum-review packets from a cohort.

The public reviewer packets deliberately contain no project identifiers, profile
names, retrieval diagnostics, model scores, or other reviewer's assessments.
The controller mapping is a separate file and must not be shared with either
expert while the review is in progress.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


_SCHEDULE_ITEM = re.compile(r"^(?P<semester>\d+)\s+(?P<title>.+)\s+(?P<credits>\d+)$")


def _anonymous_id(salt: str, index: int) -> str:
    digest = hashlib.sha256(f"{salt}:{index}".encode("utf-8")).hexdigest()[:10].upper()
    return f"P-{digest}"


def _courses(schedule: list[Any]) -> list[dict[str, Any]]:
    result = []
    for item in schedule:
        if isinstance(item, (list, tuple)) and len(item) == 3:
            semester, title, credits = item
            if isinstance(semester, int) and isinstance(title, str) and isinstance(credits, int):
                result.append({"semester": semester, "title": title, "credits": credits})
                continue
        match = _SCHEDULE_ITEM.match(str(item).strip())
        if not match:
            raise ValueError(f"Cannot parse schedule item: {item!r}")
        result.append({
            "semester": int(match.group("semester")),
            "title": match.group("title"),
            "credits": int(match.group("credits")),
        })
    return result


def _review_item(report: dict[str, Any], anonymous_plan_id: str) -> dict[str, Any]:
    variants = report.get("variants")
    if not isinstance(variants, dict) or set(variants) != {"A", "B", "C"}:
        raise ValueError("Every reviewed plan must contain exactly variants A, B and C")
    rendered_variants = {}
    for name, variant in variants.items():
        if not isinstance(variant, dict):
            raise ValueError(f"Variant {name} is not an object")
        rendered_variants[name] = {
            "credits": variant.get("credits"),
            "semester_loads": variant.get("semester_loads"),
            "courses": _courses(variant.get("schedule_fingerprint") or []),
            "bridge_modules": variant.get("bridge_titles") or [],
            "prerequisites": [
                {
                    "prerequisite_title": pair.get("prerequisite_title"),
                    "prerequisite_semester": pair.get("prerequisite_semester"),
                    "course_title": pair.get("course_title"),
                    "course_semester": pair.get("course_semester"),
                }
                for pair in (variant.get("prerequisite_pairs") or [])
            ],
        }
    scope = report.get("scope") or {}
    return {
        "anonymous_plan_id": anonymous_plan_id,
        "programme_context": {
            "level": report.get("level"),
            "jurisdiction": report.get("jurisdiction"),
            "focus": (report.get("focus") or "").strip() or None,
            "direction": scope.get("direction"),
            "group": scope.get("group"),
        },
        "variants": rendered_variants,
        "assessment": {
            "relevance": None,
            "semester": None,
            "bridge": None,
            "software_validity": None,
            "content_validity": None,
            "comment": "",
        },
    }


def build_packets(cohort: dict[str, Any], salt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if cohort.get("status") != "passed":
        raise ValueError("Refuse to prepare a blinded packet before the cohort has passed")
    reports = cohort.get("reports")
    if not isinstance(reports, list) or not reports:
        raise ValueError("Cohort must contain a non-empty reports array")
    accepted = [report for report in reports if isinstance(report, dict) and report.get("passed") is True]
    if len(accepted) != len(reports):
        raise ValueError("Refuse to prepare a blinded packet from a failed or incomplete cohort")
    ids: set[str] = set()
    items, mapping = [], []
    for index, report in enumerate(accepted, start=1):
        anonymous_id = _anonymous_id(salt, index)
        if anonymous_id in ids:
            raise ValueError("Anonymous ID collision")
        ids.add(anonymous_id)
        items.append(_review_item(report, anonymous_id))
        mapping.append({
            "anonymous_plan_id": anonymous_id,
            "cohort_index": report.get("cohort_index"),
            "temporary_project_id": report.get("temporary_project_id"),
            "temporary_version_id": report.get("temporary_version_id"),
        })
    public = {
        "format": "curriculum-kag.blind-expert-review.v1",
        "items": items,
        "instructions": {
            "rating_scale": "Rate relevance, semester and bridge from 1 (poor) to 5 (excellent).",
            "validity": "Set software_validity and content_validity to true or false independently.",
            "blindness": "Do not add model scores, candidate sources, project IDs, or another expert's ratings.",
        },
    }
    source_digest = hashlib.sha256(json.dumps(cohort, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    controller = {
        "format": "curriculum-kag.blind-expert-controller.v1",
        "source_sha256": source_digest,
        "salt_sha256": hashlib.sha256(salt.encode("utf-8")).hexdigest(),
        "items": mapping,
    }
    return public, controller


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cohort", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--salt", required=True, help="Secret controller-only value; do not share with experts")
    args = parser.parse_args()
    cohort = json.loads(args.cohort.read_text(encoding="utf-8"))
    packet, controller = build_packets(cohort, args.salt)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for reviewer in ("expert-a", "expert-b"):
        rendered = {**packet, "reviewer": reviewer}
        (args.output_dir / f"{reviewer}.packet.json").write_text(
            json.dumps(rendered, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (args.output_dir / "controller-mapping.private.json").write_text(
        json.dumps(controller, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Prepared {len(packet['items'])} independent blinded review items in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
