"""Train mined-triplet ranker and run frozen benchmarks."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def save(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run(args):
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="epvo-sbert-mined-triplets-6k")
    parser.add_argument("--triples", type=int, default=6000)
    parser.add_argument("--programmes", type=int, default=1200)
    args = parser.parse_args()
    model = ROOT / "models" / args.name
    experiment = ROOT / "experiment-results" / args.name
    classification_dir = ROOT / "experiment-results" / f"{args.name}-benchmark"
    ranking_file = ROOT / "experiment-results" / f"epvo-ranking-{args.name}" / "metrics.json"
    status_file = experiment / "run-status.json"
    status = {
        "status": "running",
        "stage": "mining_and_training",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    save(status_file, status)
    try:
        run(
            [
                "scripts/finetune_epvo_sbert_mined_triplets.py",
                "--output", str(model),
                "--triples", str(args.triples),
                "--programmes", str(args.programmes),
            ]
        )
        status["stage"] = "classification_benchmark"
        save(status_file, status)
        run(
            [
                "scripts/benchmark_epvo_sbert.py",
                "--model", str(model),
                "--output", str(classification_dir),
                "--limit", "6000",
                "--batch-size", "48",
                "--device", "cuda",
            ]
        )
        status["stage"] = "ranking_benchmark"
        save(status_file, status)
        run(
            [
                "scripts/benchmark_epvo_ranking.py",
                "--model", str(model),
                "--output", str(ranking_file),
                "--programs", "120",
                "--split", "test",
                "--device", "cuda",
            ]
        )
        classification = load(classification_dir / "metrics.json")
        ranking = load(ranking_file)
        classifier = load(
            ROOT / "experiment-results" / "epvo-sbert-cached-ranker-12k-v2-benchmark" / "metrics.json"
        )
        ranker = load(
            ROOT / "experiment-results" / "epvo-ranking-ensemble-validation-v2" / "frozen-test-baseline.json"
        )
        comparison = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "classification_test": classification["test"],
            "classification_delta_vs_best": {
                key: classification["test"][key] - classifier["test"][key]
                for key in ("roc_auc", "pr_auc", "f1")
            },
            "ranking": ranking,
            "ranking_delta_vs_best": {
                key: ranking[key] - ranker[key]
                for key in ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10")
            },
            "production_model_changed": False,
        }
        save(experiment / "comparison.json", comparison)
        status.update(
            {
                "status": "complete",
                "stage": "complete",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        save(status_file, status)
    except Exception as error:
        status.update(
            {
                "status": "failed",
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(limit=8),
            }
        )
        save(status_file, status)
        raise


if __name__ == "__main__":
    main()
