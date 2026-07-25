"""Build a lightweight reproducible baseline report before LSTM/GNN experiments."""
from __future__ import annotations

import json
import platform
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "backend" / "experiment-results"
PASSPORT = RESULTS / "dataset-passport.json"
OUTPUT_DIR = RESULTS / "reproducible-baseline"
DB = ROOT / "backend" / "curriculum_kag.db"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def table_count(db: sqlite3.Connection, table: str) -> int:
    try:
        return int(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return 0


def audit_plans(db: sqlite3.Connection) -> dict:
    db.row_factory = sqlite3.Row
    projects = []
    for project in db.execute("SELECT id,title,domain1,domain2,constraints_json FROM projects ORDER BY id"):
        version = db.execute(
            "SELECT id,status FROM project_versions WHERE project_id=? ORDER BY version_number DESC LIMIT 1",
            (project["id"],),
        ).fetchone()
        if not version:
            continue
        plans = db.execute(
            "SELECT id,variant_type,is_active,metrics_json FROM plans WHERE project_version_id=? ORDER BY id DESC",
            (version["id"],),
        ).fetchall()
        latest = {}
        for plan in plans:
            latest.setdefault(plan["variant_type"], plan)
        variants = []
        signatures = {}
        for variant, plan in sorted(latest.items()):
            items = db.execute(
                "SELECT semester,course_id,bridge_module_id,credits FROM plan_items WHERE plan_id=? ORDER BY semester,id",
                (plan["id"],),
            ).fetchall()
            metrics = json.loads(plan["metrics_json"] or "{}")
            verification = metrics.get("verification") or {}
            signatures[variant] = tuple((row["semester"], row["course_id"], row["bridge_module_id"]) for row in items)
            variants.append({
                "variant": variant,
                "plan_id": plan["id"],
                "active": bool(plan["is_active"]),
                "credits": sum(int(row["credits"] or 0) for row in items),
                "hard_violations": verification.get("hard_violation_count"),
                "lo_coverage_percentage": metrics.get("lo_coverage_percentage"),
                "min_lo_coverage": metrics.get("min_lo_coverage"),
            })
        projects.append({
            "project_id": project["id"],
            "title": project["title"],
            "status": version["status"],
            "variants": variants,
            "abc_distinct": len(set(signatures.values())) == len(signatures) if signatures else None,
        })
    return {
        "projects": projects,
        "summary": {
            "projects": len(projects),
            "plans": sum(len(row["variants"]) for row in projects),
            "non_distinct_abc": sum(row["abc_distinct"] is False for row in projects),
            "plans_with_hard_violations": sum(
                int((variant.get("hard_violations") or 0) > 0)
                for row in projects
                for variant in row["variants"]
            ),
            "active_plans_with_hard_violations": sum(
                int(bool(variant.get("active")) and (variant.get("hard_violations") or 0) > 0)
                for row in projects
                for variant in row["variants"]
            ),
        },
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    passport = read_json(PASSPORT)
    with sqlite3.connect(DB) as db:
        plan_audit = audit_plans(db)
        db_counts = {
            "courses": table_count(db, "courses"),
            "match_scores": table_count(db, "match_scores"),
            "match_feedback": table_count(db, "match_feedback"),
            "bridge_modules": table_count(db, "bridge_modules"),
            "epvo_discipline_lo_links": table_count(db, "epvo_discipline_lo_links"),
        }

    best = None
    for row in passport.get("benchmarks") or []:
        if best is None or (row.get("roc_auc") or 0) > (best.get("roc_auc") or 0):
            best = row

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Frozen baseline before LSTM/GNN/Transformer experiments",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "dataset_passport_file": str(PASSPORT),
        "dataset": {
            "seed": passport.get("seed"),
            "counts": passport.get("counts"),
            "normalized": passport.get("normalized"),
            "files": passport.get("files"),
            "split_policy": passport.get("split_policy"),
        },
        "database_counts": db_counts,
        "best_model": best,
        "all_benchmarks": passport.get("benchmarks") or [],
        "plan_audit": plan_audit,
        "readiness": {
            "dataset_frozen": bool(passport.get("files")),
            "split_recorded": bool(passport.get("counts")),
            "classification_benchmark_recorded": bool(passport.get("benchmarks")),
            "ranking_benchmark_recorded": passport.get("ranking_metrics_status") == "measured",
            "expert_feedback_loop_available": db_counts["match_feedback"] >= 0,
            "ready_for_gnn_lstm_scaffold": True,
            "active_curricula_have_no_hard_violations": plan_audit["summary"]["active_plans_with_hard_violations"] == 0,
            "ready_for_claiming_final_gnn_lstm_quality": False,
            "note": "GNN/LSTM quality must be reported only after a separate controlled run on this frozen baseline.",
        },
    }
    (OUTPUT_DIR / "baseline-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Reproducible Baseline Report",
        "",
        f"- Created: `{report['created_at']}`",
        f"- Purpose: {report['purpose']}",
        f"- Seed: `{report['dataset']['seed']}`",
        f"- Courses in repository: `{db_counts['courses']}`",
        f"- EPVO expert links: `{db_counts['epvo_discipline_lo_links']}`",
        f"- Expert feedback records: `{db_counts['match_feedback']}`",
        "",
        "## Best current model",
        "",
    ]
    if best:
        lines.extend([
            f"- Name: `{best.get('name')}`",
            f"- ROC-AUC: `{best.get('roc_auc')}`",
            f"- PR-AUC: `{best.get('pr_auc')}`",
            f"- F1: `{best.get('f1')}`",
            f"- Recall@10: `{best.get('recall_at_10')}`",
            f"- MRR: `{best.get('mrr')}`",
            f"- nDCG@10: `{best.get('ndcg_at_10')}`",
            "",
        ])
    lines.extend([
        "## Plan audit",
        "",
        f"- Projects audited: `{plan_audit['summary']['projects']}`",
        f"- Plans audited: `{plan_audit['summary']['plans']}`",
        f"- Non-distinct A/B/C projects: `{plan_audit['summary']['non_distinct_abc']}`",
        f"- Plans with hard violations: `{plan_audit['summary']['plans_with_hard_violations']}`",
        f"- Active plans with hard violations: `{plan_audit['summary']['active_plans_with_hard_violations']}`",
        "",
        "## Readiness",
        "",
    ])
    for key, value in report["readiness"].items():
        lines.append(f"- `{key}`: `{value}`")
    (OUTPUT_DIR / "baseline-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT_DIR),
        "best_model": best.get("name") if best else None,
        "plans": plan_audit["summary"]["plans"],
        "hard_violations": plan_audit["summary"]["plans_with_hard_violations"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
