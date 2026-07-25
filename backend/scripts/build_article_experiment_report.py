"""Build an article-ready reproducible report for EPVO model experiments."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "backend" / "experiment-results"
OUT = RESULTS / "article-experiment-report"


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pct(value) -> str:
    return "—" if value is None else f"{float(value) * 100:.2f}%"


def metric_row(name: str, metrics: dict, source: str) -> dict:
    test = metrics.get("test") or metrics
    return {
        "name": name,
        "source": source,
        "examples": test.get("examples"),
        "roc_auc": test.get("roc_auc"),
        "pr_auc": test.get("pr_auc"),
        "f1": test.get("f1"),
        "precision": test.get("precision"),
        "recall": test.get("recall"),
        "recall_at_10": test.get("recall_at_10"),
        "mrr": test.get("mrr"),
        "ndcg_at_10": test.get("ndcg_at_10"),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    passport = read_json(RESULTS / "dataset-passport.json")
    baseline = read_json(RESULTS / "reproducible-baseline" / "baseline-report.json")
    gnn = read_json(RESULTS / "lstm-gnn-controlled-run" / "gnn-smoke" / "metrics.json")
    lstm = read_json(RESULTS / "lstm-gnn-controlled-run" / "lstm-smoke" / "metrics.json")
    manifest = read_json(RESULTS / "lstm-gnn-controlled-run" / "manifest.json")

    rows: list[dict] = []
    for item in passport.get("benchmarks") or []:
        rows.append(metric_row(item.get("name") or "benchmark", item, "dataset-passport"))
    if gnn.get("gnn"):
        rows.append(metric_row("gnn_one_hop_smoke", gnn["gnn"], "controlled-run"))
    if lstm.get("lstm"):
        rows.append(metric_row("lstm_sequence_smoke", lstm["lstm"], "controlled-run"))

    best = baseline.get("best_model") or {}
    best_name = best.get("name") or "sbert_finetuned_40k"
    article = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title_ru": "Воспроизводимое построение образовательных программ на основе EPVO и KAG: сравнение SBERT, GNN и LSTM для связей дисциплина–результат обучения",
        "dataset": {
            "programs": (passport.get("normalized") or {}).get("raw_programs"),
            "normalized_disciplines": (passport.get("normalized") or {}).get("normalized_disciplines"),
            "expert_links": (passport.get("normalized") or {}).get("expert_links"),
            "pairs": (passport.get("counts") or {}).get("pairs"),
            "train_pairs": (passport.get("counts") or {}).get("pairs_train"),
            "validation_pairs": (passport.get("counts") or {}).get("pairs_validation"),
            "test_pairs": (passport.get("counts") or {}).get("pairs_test"),
            "split_policy": passport.get("split_policy"),
            "seed": passport.get("seed"),
            "files": passport.get("files"),
        },
        "best_model": best,
        "models": rows,
        "controlled_experiment": {
            "manifest": str((RESULTS / "lstm-gnn-controlled-run" / "manifest.json").resolve()),
            "gnn_available": bool(gnn),
            "lstm_available": bool(lstm),
            "acceptance_rule": "GNN/LSTM may replace SBERT only if ROC-AUC and PR-AUC improve and F1 does not decrease on the frozen split.",
        },
        "conclusion_ru": (
            f"На текущем frozen split лучшей рабочей моделью остаётся {best_name}. "
            "GNN/LSTM результаты сохраняются как научно значимый controlled experiment: "
            "они показывают границы применимости графовых и последовательностных моделей при текущей постановке задачи, "
            "но не внедряются в генератор, если не превосходят SBERT 40k."
        ),
    }
    (OUT / "article-experiment-report.json").write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Article experiment report",
        "",
        f"Created: `{article['created_at']}`",
        "",
        "## Suggested title",
        "",
        article["title_ru"],
        "",
        "## Dataset",
        "",
        f"- EPVO programmes: `{article['dataset']['programs']}`",
        f"- Normalized disciplines: `{article['dataset']['normalized_disciplines']}`",
        f"- Expert course–LO links: `{article['dataset']['expert_links']}`",
        f"- Pairs: `{article['dataset']['pairs']}`",
        f"- Split: `{article['dataset']['split_policy']}`",
        f"- Seed: `{article['dataset']['seed']}`",
        "",
        "## Model comparison",
        "",
        "| Model | Source | Examples | ROC-AUC | PR-AUC | F1 | Recall@10 | MRR | nDCG@10 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['source']} | {row.get('examples') or '—'} | "
            f"{pct(row.get('roc_auc'))} | {pct(row.get('pr_auc'))} | {pct(row.get('f1'))} | "
            f"{pct(row.get('recall_at_10'))} | {pct(row.get('mrr'))} | {pct(row.get('ndcg_at_10'))} |"
        )
    lines.extend([
        "",
        "## Methodological guardrail",
        "",
        article["controlled_experiment"]["acceptance_rule"],
        "",
        "## Draft conclusion",
        "",
        article["conclusion_ru"],
        "",
        "## Reproducibility",
        "",
        f"- Baseline report: `{(RESULTS / 'reproducible-baseline' / 'baseline-report.json').resolve()}`",
        f"- Controlled manifest: `{(RESULTS / 'lstm-gnn-controlled-run' / 'manifest.json').resolve()}`",
        f"- Dataset passport: `{(RESULTS / 'dataset-passport.json').resolve()}`",
    ])
    (OUT / "article-experiment-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "models": len(rows), "lstm_available": bool(lstm)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
