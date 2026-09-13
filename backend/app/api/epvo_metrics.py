"""Pure model-comparison helpers used by EPVO reporting endpoints."""

from __future__ import annotations

import json
from pathlib import Path


def metric_delta(candidate: dict | None, baseline: dict | None) -> dict:
    candidate = candidate or {}
    baseline = baseline or {}
    keys = ("roc_auc", "pr_auc", "f1")
    deltas = {key: round(float(candidate.get(key) or 0) - float(baseline.get(key) or 0), 6) for key in keys}
    beats = all(deltas[key] > 0 for key in ("roc_auc", "pr_auc")) and deltas["f1"] >= 0
    return {
        "deltas": deltas,
        "beats_baseline": beats,
        "decision": "candidate_can_be_integrated" if beats else "keep_as_experiment",
        "guardrail": "Integrate only if ROC-AUC and PR-AUC improve and F1 does not decrease on the frozen split.",
    }


def best_model_from_baseline(report_file: Path) -> dict:
    if not report_file.exists():
        return {}
    try:
        return json.loads(report_file.read_text(encoding="utf-8")).get("best_model") or {}
    except (OSError, ValueError):
        return {}
