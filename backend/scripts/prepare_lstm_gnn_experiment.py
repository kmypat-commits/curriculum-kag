"""Prepare a controlled LSTM/GNN experiment manifest without running training."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "backend" / "experiment-results"
BASELINE = RESULTS / "reproducible-baseline" / "baseline-report.json"
OUTPUT = RESULTS / "lstm-gnn-controlled-run"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "prepared_not_started",
        "purpose": "Controlled local LSTM/GNN experiment after stable Dataset Passport and baseline",
        "baseline_report": str(BASELINE),
        "frozen_dataset": {
            "split_policy": (baseline.get("dataset") or {}).get("split_policy"),
            "seed": (baseline.get("dataset") or {}).get("seed"),
            "files": (baseline.get("dataset") or {}).get("files"),
            "counts": (baseline.get("dataset") or {}).get("counts"),
        },
        "current_best_model": baseline.get("best_model"),
        "experiments": [
            {
                "name": "gnn_one_hop_pilot",
                "status": "smoke_complete_or_ready",
                "script": "backend/scripts/train_epvo_gnn_pilot.py",
                "safe_smoke_command": (
                    "python backend/scripts/train_epvo_gnn_pilot.py "
                    "--program-limit 80 --epochs 10 "
                    "--output backend/experiment-results/lstm-gnn-controlled-run/gnn-smoke"
                ),
                "full_command": (
                    "python backend/scripts/train_epvo_gnn_pilot.py "
                    "--program-limit 600 --epochs 60 "
                    "--output backend/experiment-results/lstm-gnn-controlled-run/gnn-full"
                ),
                "leakage_control": "Programme-level split; target edges removed before one-hop aggregation.",
            },
            {
                "name": "lstm_sequence_pilot",
                "status": "ready_for_smoke",
                "script": "backend/scripts/train_epvo_lstm_pilot.py",
                "safe_smoke_command": (
                    "python backend/scripts/train_epvo_lstm_pilot.py "
                    "--program-limit 40 --epochs 3 "
                    "--output backend/experiment-results/lstm-gnn-controlled-run/lstm-smoke"
                ),
                "full_command": (
                    "python backend/scripts/train_epvo_lstm_pilot.py "
                    "--program-limit 300 --epochs 30 "
                    "--output backend/experiment-results/lstm-gnn-controlled-run/lstm-full"
                ),
                "input": "Frozen programme/course/LO sequences from EPVO split files",
                "planned_output": "metrics.json with ROC-AUC, PR-AUC, F1",
                "leakage_control": "Programme-level split; test programmes are never used for training.",
                "guardrail": "Do not compare as final dissertation result until run on the same frozen baseline split.",
            },
        ],
        "acceptance_criteria": {
            "must_beat_current_best_roc_auc": (baseline.get("best_model") or {}).get("roc_auc"),
            "must_report_ranking_metrics": True,
            "must_save_metrics_json": True,
            "must_save_seed_and_command": True,
            "must_not_train_on_test_programmes": True,
        },
        "next_manual_step": "Run smoke commands first; only run full GPU training if smoke metrics are produced and the machine is stable.",
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT / "README_RU.md").write_text(
        "\n".join([
            "# LSTM/GNN controlled experiment",
            "",
            "Эксперимент подготовлен, но тяжёлое обучение не запускается автоматически.",
            "",
            "## Безопасный GNN smoke-запуск",
            "",
            "```powershell",
            manifest["experiments"][0]["safe_smoke_command"],
            "```",
            "",
            "## Безопасный LSTM smoke-запуск",
            "",
            "```powershell",
            manifest["experiments"][1]["safe_smoke_command"],
            "```",
            "",
            "## Полный GNN запуск",
            "",
            "```powershell",
            manifest["experiments"][0]["full_command"],
            "```",
            "",
            "## Полный LSTM запуск",
            "",
            "```powershell",
            manifest["experiments"][1]["full_command"],
            "```",
            "",
            "## Правило",
            "",
            "Нельзя заявлять итоговое качество GNN/LSTM, пока эксперимент не выполнен на frozen split из baseline report.",
        ]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(OUTPUT), "status": manifest["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
