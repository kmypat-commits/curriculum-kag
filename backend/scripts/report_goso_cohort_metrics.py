"""Compare fresh curriculum-validation metrics with and without SCES RK (GOSO).

The cohort split is based on the presence of protected regulatory courses in
the generated plan. Only quality-eligible rows are included; negative-control
programmes remain visible in the source report but do not affect cohort means.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean


METRICS = (
    "epvo_provenance",
    "epvo_provenance_excluding_regulatory",
    "semester_alignment_pm1",
    "semester_alignment_prereq_adjusted_pm1",
    "semester_alignment_semantic_adjusted_pm1",
    "international_score",
    "hard_violations",
    "top5_mean_jaccard",
)


def _mean(rows: list[dict], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return round(mean(values), 4) if values else None


def summarize(rows: list[dict]) -> dict:
    return {
        "programme_count": len(rows),
        "project_ids": [int(row["project_id"]) for row in rows],
        "metrics": {key: _mean(rows, key) for key in METRICS},
        "plan_courses": sum(int(row.get("plan_courses") or 0) for row in rows),
        "epvo_courses": sum(int(row.get("epvo_courses") or 0) for row in rows),
        "protected_regulatory_courses": sum(
            int(row.get("regulatory_real_courses_excluded") or 0) for row in rows
        ),
        "feasible_programmes": sum(bool(row.get("feasible")) for row in rows),
        "distinct_variant_programmes": sum(
            bool(row.get("variants_are_distinct")) for row in rows
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(
            "backend/experiment-results/external-epvo-plan-validation/"
            "fresh-semester-ceiling.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "backend/experiment-results/external-epvo-plan-validation/"
            "goso-vs-international-metrics.json"
        ),
    )
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    projects = payload.get("projects") or []
    eligible = [row for row in projects if row.get("quality_eligible")]
    without_goso = [
        row for row in eligible if not int(row.get("regulatory_real_courses_excluded") or 0)
    ]
    with_goso = [
        row for row in eligible if int(row.get("regulatory_real_courses_excluded") or 0)
    ]

    report = {
        "source": str(args.input).replace("\\", "/"),
        "cohort_rule": (
            "quality_eligible=true; with_goso iff protected regulatory course count > 0"
        ),
        "negative_controls_excluded": [
            int(row["project_id"])
            for row in projects
            if not row.get("quality_eligible")
        ],
        "without_goso": summarize(without_goso),
        "with_goso": summarize(with_goso),
    }
    report["difference_without_minus_with"] = {
        key: round(
            float(report["without_goso"]["metrics"][key])
            - float(report["with_goso"]["metrics"][key]),
            4,
        )
        for key in METRICS
        if report["without_goso"]["metrics"][key] is not None
        and report["with_goso"]["metrics"][key] is not None
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
