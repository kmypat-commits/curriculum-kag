"""Build a reproducible Dataset Passport and model benchmark summary."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "backend" / "experiment-results"
LABELS = RESULTS / "epvo-expert-labels"
OUTPUT = RESULTS / "dataset-passport.json"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Build a CEER Dataset Passport from the selected database.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'backend' / 'curriculum_kag.db'}"),
        help="SQLAlchemy URL; defaults to DATABASE_URL or the local SQLite rollback database.",
    )
    parser.add_argument(
        "--labels-dir",
        type=Path,
        default=LABELS,
        help="Frozen CEER JSONL export containing manifest.json and pair files.",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    labels_dir = args.labels_dir.resolve()
    manifest_path = labels_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(
            f"Frozen CEER export is required: {manifest_path}. "
            "Pass --labels-dir with the archived or released CEER export; no passport was created."
        )
    manifest = read(manifest_path)
    benchmark_paths = {
        "sbert_finetuned_40k": RESULTS / "epvo-sbert-finetuned-40k-benchmark" / "metrics.json",
        "sbert_base": RESULTS / "epvo-sbert-benchmark" / "metrics.json",
        "expert_head": RESULTS / "epvo-sbert-expert-head" / "metrics.json",
    }
    benchmarks = []
    ranking_path = RESULTS / "epvo-ranking-benchmark" / "metrics.json"
    ranking = read(ranking_path) if ranking_path.exists() else {}
    for name, path in benchmark_paths.items():
        if not path.exists():
            continue
        payload = read(path)
        test = payload.get("test") or {}
        benchmarks.append({
            "name": name, "model": payload.get("model"), "device": payload.get("device"),
            "examples": test.get("examples"), "roc_auc": test.get("roc_auc"), "pr_auc": test.get("pr_auc"),
            "f1": test.get("f1"), "precision": test.get("precision"), "recall": test.get("recall"),
            "accuracy": test.get("accuracy"), "threshold": test.get("threshold"),
            "recall_at_5": ranking.get("recall_at_5") if name == "sbert_finetuned_40k" else None,
            "recall_at_10": ranking.get("recall_at_10") if name == "sbert_finetuned_40k" else None,
            "mrr": ranking.get("mrr") if name == "sbert_finetuned_40k" else None,
            "ndcg_at_10": ranking.get("ndcg_at_10") if name == "sbert_finetuned_40k" else None,
        })
    engine = create_engine(args.database_url)
    with engine.connect() as db:
        def count(table):
            return int(db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
        normalized = {
            "raw_programs": count("raw_epvo_programs"), "raw_disciplines": count("raw_epvo_disciplines"),
            "raw_learning_outcomes": count("raw_epvo_learning_outcomes"), "raw_expert_checks": count("raw_epvo_expert_checks"),
            "directions": count("epvo_directions"), "groups": count("epvo_groups"),
            "normalized_disciplines": count("epvo_disciplines_normalized"), "expert_links": count("epvo_discipline_lo_links"),
            "expert_feedback": count("match_feedback"),
        }
    files = []
    for name in ("course_lo_pairs.jsonl", "programs.jsonl"):
        path = labels_dir / name
        if not path.exists():
            raise SystemExit(
                f"Frozen CEER export is incomplete: {path}. No passport was created."
            )
        files.append({"name": name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    passport = {
        "created_at": datetime.now(timezone.utc).isoformat(), "dataset": "CEER graded discipline-LO evidence",
        "database_dialect": engine.dialect.name,
        "seed": manifest.get("seed"), "counts": manifest.get("counts"), "normalized": normalized,
        "files": files, "split_policy": "program-level train/validation/test split from the frozen EPVO manifest",
        "benchmarks": benchmarks,
        "ranking_metrics_status": "measured" if ranking else "not_measured",
        "ranking_metrics_note": "Ranking metrics use a deterministic sample of frozen test programmes and are not inferred from classification metrics.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(passport, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "benchmarks": len(benchmarks), "files": len(files), **normalized}, ensure_ascii=False))


if __name__ == "__main__":
    main()
