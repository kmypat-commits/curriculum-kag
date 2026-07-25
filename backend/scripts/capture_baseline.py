"""Create a timestamped SQLite backup and reproducible curriculum baseline."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DB = ROOT / "backend" / "curriculum_kag.db"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parsed(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    parser.add_argument(
        "--no-backup", action="store_true",
        help="Audit the live database read-only without duplicating the large EPVO tables.",
    )
    parser.add_argument("--skip-quick-check", action="store_true")
    parser.add_argument("--skip-sha256", action="store_true")
    args = parser.parse_args()
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output = Path(args.output) if args.output else ROOT / "backups" / f"baseline-{stamp}"
    output.mkdir(parents=True, exist_ok=True)
    backup_db = output / "curriculum_kag.db"

    if not args.no_backup:
        with sqlite3.connect(SOURCE_DB) as source, sqlite3.connect(backup_db) as target:
            source.backup(target)
    audited_db = SOURCE_DB if args.no_backup else backup_db
    with sqlite3.connect(f"file:{audited_db.as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        # The live database includes multi-gigabyte raw EPVO tables. Scanning
        # every page defeats the purpose of a lightweight plan audit.
        quick_check = (
            "not_run_live_large_db"
            if args.no_backup
            else "skipped"
            if args.skip_quick_check
            else db.execute("PRAGMA quick_check").fetchone()[0]
        )
        projects = []
        for project in db.execute("SELECT * FROM projects ORDER BY id"):
            version = db.execute(
                "SELECT * FROM project_versions WHERE project_id=? ORDER BY version_number DESC LIMIT 1",
                (project["id"],),
            ).fetchone()
            constraints = parsed(project["constraints_json"], {})
            variants = []
            schedules = {}
            if version:
                plans = db.execute(
                    "SELECT * FROM plans WHERE project_version_id=? ORDER BY id DESC",
                    (version["id"],),
                ).fetchall()
                latest = {}
                for plan in plans:
                    latest.setdefault(plan["variant_type"], plan)
                for variant, plan in sorted(latest.items()):
                    items = db.execute(
                        """SELECT pi.*, c.title, c.domain
                           FROM plan_items pi LEFT JOIN courses c ON c.id=pi.course_id
                           WHERE pi.plan_id=? ORDER BY pi.semester, pi.id""",
                        (plan["id"],),
                    ).fetchall()
                    signature = [(row["semester"], row["course_id"], row["bridge_module_id"]) for row in items]
                    schedules[variant] = signature
                    loads = {}
                    titles = []
                    foreign = []
                    prerequisite_violations = []
                    semester_by_course = {row["course_id"]: row["semester"] for row in items if row["course_id"]}
                    domains = [str(project["domain1"] or "").lower(), str(project["domain2"] or "").lower()]
                    for row in items:
                        loads[row["semester"]] = loads.get(row["semester"], 0) + int(row["credits"] or 0)
                        if row["title"]:
                            titles.append(" ".join(row["title"].lower().split()))
                        domain = str(row["domain"] or "").lower()
                        if domain and not any(d and (d in domain or domain in d) for d in domains):
                            foreign.append(row["title"])
                        for prerequisite in parsed(row["prerequisites_snapshot"], []):
                            if prerequisite in semester_by_course and semester_by_course[prerequisite] >= row["semester"]:
                                prerequisite_violations.append([prerequisite, row["course_id"]])
                    metrics = parsed(plan["metrics_json"], {})
                    target = int(constraints.get("total_credits", 0) or 0)
                    total = sum(loads.values())
                    variants.append({
                        "variant": variant, "plan_id": plan["id"], "active": bool(plan["is_active"]),
                        "credits": total, "credit_delta": total - target, "semester_loads": loads,
                        "duplicate_titles": len(titles) - len(set(titles)),
                        "prerequisite_violations": prerequisite_violations,
                        "foreign_domain_courses": sorted(set(filter(None, foreign))),
                        "lo_coverage_percentage": metrics.get("lo_coverage_percentage"),
                        "min_lo_coverage": metrics.get("min_lo_coverage"),
                        "feasible": (metrics.get("verification") or {}).get("feasible"),
                    })
            projects.append({
                "project_id": project["id"], "title": project["title"],
                "version_id": version["id"] if version else None,
                "status": version["status"] if version else None,
                "constraints": constraints, "variants": variants,
                "abc_distinct": len({tuple(value) for value in schedules.values()}) == len(schedules) if schedules else None,
            })

    manifest = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "database": {"source": str(SOURCE_DB),
                     "backup": None if args.no_backup else backup_db.name,
                     "bytes": audited_db.stat().st_size,
                     "sha256": None if args.no_backup or args.skip_sha256 else sha256(backup_db),
                     "sha256_status": "skipped" if args.no_backup or args.skip_sha256 else "ok",
                     "quick_check": quick_check},
        "summary": {
            "projects": len(projects),
            "projects_with_non_distinct_abc": sum(p["abc_distinct"] is False for p in projects),
            "plans_with_duplicates": sum(v["duplicate_titles"] > 0 for p in projects for v in p["variants"]),
            "plans_with_prerequisite_violations": sum(bool(v["prerequisite_violations"]) for p in projects for v in p["variants"]),
            "plans_with_foreign_domains": sum(bool(v["foreign_domain_courses"]) for p in projects for v in p["variants"]),
        },
        "projects": projects,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), **manifest["summary"], "quick_check": quick_check}, ensure_ascii=False))


if __name__ == "__main__":
    main()
