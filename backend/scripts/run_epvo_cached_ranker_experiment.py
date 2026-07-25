"""Run training and frozen classification/ranking benchmarks as one job."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run(command: list[str]) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="epvo-sbert-cached-ranker-12k")
    parser.add_argument("--pairs", type=int, default=12000)
    parser.add_argument("--virtual-batch-size", type=int, default=32)
    parser.add_argument("--mini-batch-size", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=5e-7)
    args = parser.parse_args()

    model = ROOT / "models" / args.name
    experiment = ROOT / "experiment-results" / args.name
    classifier_output = ROOT / "experiment-results" / f"{args.name}-benchmark"
    ranking_output = ROOT / "experiment-results" / f"epvo-ranking-{args.name}" / "metrics.json"
    status_path = experiment / "run-status.json"
    started = datetime.now(timezone.utc).isoformat()
    status = {
        "status": "running",
        "started_at": started,
        "stage": "training",
        "model": str(model),
        "pairs": args.pairs,
        "virtual_batch_size": args.virtual_batch_size,
        "mini_batch_size": args.mini_batch_size,
        "learning_rate": args.learning_rate,
    }
    write_json(status_path, status)

    try:
        run(
            [
                sys.executable,
                "scripts/finetune_epvo_sbert_cached_ranker.py",
                "--model",
                "models/epvo-sbert-finetuned-40k",
                "--output",
                str(model),
                "--pairs",
                str(args.pairs),
                "--virtual-batch-size",
                str(args.virtual_batch_size),
                "--mini-batch-size",
                str(args.mini_batch_size),
                "--learning-rate",
                str(args.learning_rate),
            ]
        )
        status["stage"] = "classification_benchmark"
        write_json(status_path, status)
        run(
            [
                sys.executable,
                "scripts/benchmark_epvo_sbert.py",
                "--model",
                str(model),
                "--output",
                str(classifier_output),
                "--limit",
                "6000",
                "--batch-size",
                "48",
                "--device",
                "cuda",
            ]
        )
        status["stage"] = "ranking_benchmark"
        write_json(status_path, status)
        run(
            [
                sys.executable,
                "scripts/benchmark_epvo_ranking.py",
                "--model",
                str(model),
                "--output",
                str(ranking_output),
                "--programs",
                "80",
                "--device",
                "cuda",
            ]
        )

        classification = load(classifier_output / "metrics.json")
        ranking = load(ranking_output)
        classifier_baseline = load(
            ROOT / "experiment-results" / "epvo-sbert-finetuned-40k-benchmark" / "metrics.json"
        )
        ranker_baseline = load(
            ROOT / "experiment-results" / "epvo-ranking-ranking-loss-pilot" / "metrics.json"
        )
        rank_metrics = ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10")
        rank_deltas = {
            metric: ranking[metric] - ranker_baseline[metric] for metric in rank_metrics
        }
        classification_metrics = ("roc_auc", "pr_auc", "f1")
        classification_deltas = {
            metric: classification["test"][metric] - classifier_baseline["test"][metric]
            for metric in classification_metrics
        }
        improved_rank_metrics = sum(delta > 0 for delta in rank_deltas.values())
        no_material_rank_regression = min(rank_deltas.values()) >= -0.002
        comparison = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "candidate": args.name,
            "classification_test": classification["test"],
            "classification_baseline": classifier_baseline["test"],
            "classification_delta": classification_deltas,
            "ranking": ranking,
            "ranking_baseline": ranker_baseline,
            "ranking_delta": rank_deltas,
            "recommended_as_reranker_candidate": (
                improved_rank_metrics >= 3 and no_material_rank_regression
            ),
            "selection_rule": (
                "improve at least 3/4 frozen ranking metrics and do not regress any "
                "ranking metric by more than 0.002; production promotion remains manual"
            ),
            "production_model_changed": False,
        }
        write_json(experiment / "comparison.json", comparison)
        status.update(
            {
                "status": "complete",
                "stage": "complete",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "comparison": str(experiment / "comparison.json"),
                "recommended_as_reranker_candidate": comparison[
                    "recommended_as_reranker_candidate"
                ],
            }
        )
        write_json(status_path, status)
        print(json.dumps(status, ensure_ascii=False), flush=True)
    except Exception as error:
        status.update(
            {
                "status": "failed",
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(limit=8),
            }
        )
        write_json(status_path, status)
        raise


if __name__ == "__main__":
    main()
