"""Reproducible clean-target SQLite -> PostgreSQL acceptance orchestrator."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HASH_TABLES = [
    "users", "projects", "project_versions", "learning_outcomes", "courses",
    "course_localizations", "raw_epvo_programs", "raw_epvo_disciplines",
    "raw_epvo_learning_outcomes", "raw_epvo_expert_checks", "epvo_directions",
    "epvo_groups", "epvo_disciplines_normalized", "epvo_discipline_lo_links",
    "epvo_prerequisites",
]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_sqlite_url(source: Path) -> str:
    """Return an absolute SQLAlchemy SQLite URL independent of cwd."""
    resolved = source if source.is_absolute() else ROOT / source
    return "sqlite:///" + resolved.resolve().as_posix()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "backend" / "curriculum_kag.db")
    parser.add_argument("--target", required=True, help="Empty PostgreSQL URL; existing non-empty targets are rejected")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--orphan-manifest",
        type=Path,
        help="Reviewed source-specific FK manifest passed to the migration step",
    )
    parser.add_argument("--restore", action="store_true", help="Run isolated pg_dump/pg_restore round-trip after compare")
    args = parser.parse_args()
    if not args.target.startswith("postgresql"):
        raise SystemExit("--target must be a PostgreSQL URL")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "backend")
    source_path = args.source if args.source.is_absolute() else ROOT / args.source
    source_hash_before = file_sha256(source_path.resolve())
    source_url = source_sqlite_url(args.source)
    migrate_command = [
        sys.executable, str(ROOT / "backend" / "scripts" / "migrate_sqlite_to_postgres.py"),
        "--source", source_url, "--target", args.target, "--batch-size", "250",
    ]
    if args.orphan_manifest is not None:
        migrate_command.extend(["--orphan-manifest", str(args.orphan_manifest)])
    migrate = subprocess.run(
        migrate_command, cwd=ROOT, env=env, capture_output=True, text=True
    )
    if migrate.returncode:
        raise SystemExit((migrate.stderr or migrate.stdout)[-4000:])
    source_hash_after_migration = file_sha256(source_path.resolve())
    if source_hash_after_migration != source_hash_before:
        raise SystemExit("SQLite source changed during migration; acceptance aborted")
    compare = subprocess.run([
        sys.executable, str(ROOT / "backend" / "scripts" / "compare_sqlite_postgres_counts.py"),
        "--sqlite", str(source_path.resolve()), "--postgres", args.target, "--hash", "--check-fk",
        "--allow-sqlite-fk-violations", "--output", str(args.output),
        "--tables", *HASH_TABLES,
    ], cwd=ROOT, env=env, capture_output=True, text=True)
    if compare.returncode:
        raise SystemExit((compare.stderr or compare.stdout)[-4000:])
    source_hash_after_compare = file_sha256(source_path.resolve())
    if source_hash_after_compare != source_hash_before:
        raise SystemExit("SQLite source changed during comparison; acceptance aborted")
    report = json.loads(compare.stdout)
    report["migration"] = "sqlite_to_postgres_clean_target"
    report["source"] = str(args.source)
    report["source_sha256"] = source_hash_before
    report["target"] = "redacted"
    if args.restore:
        restore = subprocess.run([
            sys.executable, str(ROOT / "backend" / "scripts" / "check_postgres_restore.py"),
        ], cwd=ROOT, env={**env, "DATABASE_URL": args.target}, capture_output=True, text=True)
        report["restore"] = {"passed": restore.returncode == 0, "output_tail": (restore.stdout or restore.stderr)[-2000:]}
        if restore.returncode:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return restore.returncode
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "hash_tables": len(HASH_TABLES), "restore": bool(args.restore)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
