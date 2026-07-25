"""Train and benchmark the programme-aware EPVO reranker."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run(command: list[str]) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="epvo-sbert-program-ranker-8k")
    parser.add_argument("--pairs", type=int, default=8000)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--mini-batch-size", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=5e-7)
    args = parser.parse_args()

    model = ROOT / "models" / args.name
    experiment = ROOT / "experiment-results" / args.name
    classification_dir = ROOT / "experiment-results" / f"{args.name}-benchmark"
    ranking_file = ROOT / "experiment-results" / f"epvo-ranking-{args.name}" / "metrics.json"
    status_file = experiment / "run-status.json"
    status = {
        "status": "running",
        "stage": "training",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": str(model),
        "pairs": args.pairs,
        "batch_size": args.batch_size,
    }
    save(status_file, status)
    try:
        run(
            [
                sys.executable,
                "scripts/finetune_epvo_sbert_program_ranker.py",
                "--output",
                str(model),
                "--pairs",
                str(args.pairs),
                "--batch-size",
                str(args.batch_size),
                "--mini-batch-size",
                str(args.mini_batch_size),
                "--learning-rate",
                str(args.learning_rate),
            ]
        )
        status["stage"] = "classification_benchmark"
        save(status_file, status)
        run(
            [
                sys.executable,
                "scripts/benchmark_epvo_sbert.py",
                "--model",
                str(model),
                "--output",
                str(classification_dir),
                "--limit",
                "6000",
                "--batch-size",
                "48",
                "--device",
                "cuda",
            ]
        )
        status["stage"] = "ranking_benchmark"
        save(status_file, status)
        run(
            [
                sys.executable,
                "scripts/benchmark_epvo_ranking.py",
                "--model",
                str(model),
                "--output",
                str(ranking_file),
                "--programs",
                "80",
                "--device",
                "cuda",
            ]
        )
        classification = load(classification_dir / "metrics.json")
        ranking = load(ranking_file)
        best_classifier = load(
            ROOT / "experiment-results" / "epvo-sbert-cached-ranker-12k-v2-benchmark" / "metrics.json"
        )
        best_ranker = load(
            ROOT / "experiment-results" / "epvo-ranking-ranking-loss-pilot" / "metrics.json"
        )
        rank_keys = ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10")
        rank_delta = {key: ranking[key] - best_ranker[key] for key in rank_keys}
        comparison = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "candidate": args.name,
            "classification_test": classification["test"],
            "best_classifier_test": best_classifier["test"],
            "classification_delta": {
                key: classification["test"][key] - best_classifier["test"][key]
                for key in ("roc_auc", "pr_auc", "f1")
            },
            "ranking": ranking,
            "best_ranker": best_ranker,
            "ranking_delta": rank_delta,
            "recommended_as_reranker_candidate": (
                sum(value > 0 for value in rank_delta.values()) >= 3
                and min(rank_delta.values()) >= -0.002
            ),
            "production_model_changed": False,
        }
        save(experiment / "comparison.json", comparison)
        status.update(
            {
                "status": "complete",
                "stage": "complete",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "recommended_as_reranker_candidate": comparison[
                    "recommended_as_reranker_candidate"
                ],
            }
        )
        save(status_file, status)
    except Exception as error:
        status.update(
            {
                "status": "failed",
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(limit=8),
            }
        )
        save(status_file, status)
        raise


if __name__ == "__main__":
    main()
