"""Evaluate leakage-safe empirical-Bayes priors for EPVO expert scores."""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error


def norm(value):
    return " ".join(re.findall(r"\w+", str(value or "").casefold()))


def title(row):
    values = row.get("course_title") or {}
    return norm(values.get("ru") or values.get("kz") or values.get("en"))


def add(stats, key, score):
    value = stats[key]
    value[0] += score; value[1] += 1


def smooth(stats, key, prior, alpha):
    total, count = stats.get(key, (0.0, 0))
    return (total + alpha * prior) / (count + alpha), count


def level(score):
    return 0 if score < 0.25 else 1 if score < 0.75 else 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiment-results/epvo-expert-labels/course_lo_pairs.jsonl")
    parser.add_argument("--output", default="experiment-results/epvo-hierarchical-prior")
    args = parser.parse_args()
    source, output = Path(args.input), Path(args.output); output.mkdir(parents=True, exist_ok=True)
    university, course, course_lo, university_lo = (defaultdict(lambda: [0.0, 0]) for _ in range(4))
    total = count = 0
    with source.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line); score = row.get("expert_score")
            if row.get("split") != "train" or score is None: continue
            score = float(score); uni = str(row.get("university_id")); name = title(row); code = norm(row.get("lo_code"))
            total += score; count += 1
            add(university, uni, score); add(course, name, score)
            add(course_lo, (name, code), score); add(university_lo, (uni, code), score)
    global_mean = total / max(count, 1)

    results = {}
    for split in ("validation", "test"):
        actual, predicted = [], []
        with source.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line); score = row.get("expert_score")
                if row.get("split") != split or score is None: continue
                uni = str(row.get("university_id")); name = title(row); code = norm(row.get("lo_code"))
                u, uc = smooth(university, uni, global_mean, 30)
                c, cc = smooth(course, name, u, 20)
                ul, ulc = smooth(university_lo, (uni, code), u, 20)
                cl, clc = smooth(course_lo, (name, code), c, 12)
                # Reliability-weighted blend: exact course/LO history wins;
                # otherwise university practice and course history dominate.
                weights = np.asarray([1.0, min(3.0, math.log1p(cc)), min(2.0, math.log1p(ulc)), min(4.0, math.log1p(clc))])
                values = np.asarray([global_mean, c, ul, cl])
                prediction = float(np.dot(weights, values) / weights.sum())
                actual.append(float(score)); predicted.append(prediction)
        a, p = np.asarray(actual), np.asarray(predicted)
        results[split] = {
            "examples": len(a), "mae": round(float(mean_absolute_error(a, p)), 6),
            "rmse": round(float(math.sqrt(mean_squared_error(a, p))), 6),
            "within_0.25": round(float(np.mean(np.abs(a - p) <= 0.25)), 6),
            "level_accuracy": round(float(np.mean([level(x) == level(y) for x, y in zip(a, p)])), 6),
        }
    metrics = {
        "created_at": datetime.now(timezone.utc).isoformat(), "model_type": "hierarchical_empirical_bayes",
        "training_examples": count, "global_mean": global_mean, **results,
        "note": "Benchmark uses training-program history only; validation and test programs remain unseen.",
    }
    (output / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__": main()
