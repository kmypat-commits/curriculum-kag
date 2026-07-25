"""Run the multi-positive pilot and frozen raw/scoped ranking benchmarks."""
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


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="epvo-sbert-multipositive-listwise-pilot")
    parser.add_argument("--groups", type=int, default=1000)
    parser.add_argument("--batch-groups", type=int, default=3)
    args = parser.parse_args()
    model = ROOT / "models" / args.name
    experiment = ROOT / "experiment-results" / args.name
    status_path = experiment / "run-status.json"
    status = {
        "status": "running",
        "stage": "training",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": str(model),
        "groups": args.groups,
        "production_model_changed": False,
    }
    save(status_path, status)
    try:
        run([
            sys.executable, "scripts/finetune_epvo_sbert_multipositive_ranker.py",
            "--output", str(model), "--groups", str(args.groups),
            "--batch-groups", str(args.batch_groups),
        ])
        status["stage"] = "raw_ranking_benchmark"
        save(status_path, status)
        raw_path = experiment / "raw-ranking.json"
        run([
            sys.executable, "scripts/benchmark_epvo_ranking.py",
            "--model", str(model), "--output", str(raw_path),
            "--programs", "120", "--device", "cuda",
        ])
        status["stage"] = "scoped_memory_benchmark"
        save(status_path, status)
        scoped_dir = ROOT / "experiment-results" / f"{args.name}-scoped-memory"
        run([
            sys.executable, "scripts/benchmark_epvo_scoped_memory_ranking.py",
            "--model", str(model), "--output", str(scoped_dir / "metrics.json"),
            "--programmes", "120", "--per-key-limit", "64", "--batch-size", "24",
        ])
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        scoped = json.loads((scoped_dir / "metrics.json").read_text(encoding="utf-8"))
        comparison = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "method": "programme-wise multi-positive listwise SBERT",
            "raw": raw,
            "scoped_test": scoped.get("frozen_test"),
            "selected_weights": {
                "global": scoped.get("selected_global_weight"),
                "scope": scoped.get("selected_scoped_weight"),
            },
            "production_model_changed": False,
        }
        save(experiment / "comparison.json", comparison)
        status.update({"status": "complete", "stage": "complete", "completed_at": datetime.now(timezone.utc).isoformat()})
        save(status_path, status)
    except Exception as error:
        status.update({
            "status": "failed", "failed_at": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc(limit=8),
        })
        save(status_path, status)
        raise


if __name__ == "__main__":
    main()
