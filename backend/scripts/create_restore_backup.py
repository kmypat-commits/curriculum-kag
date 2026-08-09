"""Create a compact local restore point without duplicating the EPVO dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INCLUDE_PATHS = [
    "backend/app", "backend/migrations", "backend/tests", "backend/scripts",
    "backend/ml", "backend/alembic.ini", "backend/requirements.txt",
    "backend/requirements-local.txt", "backend/requirements-minimal.txt",
    "backend/init_db.sql", "backend/scripts/legacy/init_db_data.py", "backend/scripts/legacy/seed_db.py",
    "backend/scripts/legacy/seed_investigator.py", "backend/scripts/legacy/seed_massive_210.py",
    "backend/scripts/legacy/seed_massive_210_en.py", "backend/.env", "backend/curriculum_kag.db",
    "frontend/src", "frontend/index.html", "frontend/package.json",
    "frontend/package-lock.json", "frontend/vite.config.js",
    "frontend/Dockerfile.dev", "start.ps1", "start.bat", "stop.ps1", "stop.bat",
    "docker-compose.yml", "download_epvo.bat", "epvo_status.bat", "epvo_ai_status.bat",
    "README.md", "QUICKSTART.md", "LOCAL_SETUP.md", "USER_GUIDE_RU.md",
    "THESIS_ALIGNMENT_RU.md", "THESIS_ALIGNMENT_CURRENT_RU.md",
    "IMPLEMENTATION_STATUS_RU.md", "DEVELOPMENT_ROADMAP_RU.md", "EPVO_DATASET_RU.md",
    "POSTGRES_GRAPH_STATUS_RU.md", "CODEX_CONTEXT_RU.md",
    "backend/models/epvo-sbert-finetuned-40k",
]

EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", "node_modules", "venv", ".runtime"}


def iter_files(skip_large_state=False):
    large_state_paths = {
        "backend/curriculum_kag.db",
        "backend/models/epvo-sbert-finetuned-40k",
    }
    seen = set()
    for relative in INCLUDE_PATHS:
        if skip_large_state and any(relative == path or relative.startswith(f"{path}/") for path in large_state_paths):
            continue
        path = ROOT / relative
        candidates = path.rglob("*") if path.is_dir() else [path]
        for candidate in candidates:
            if not candidate.is_file() or any(part in EXCLUDED_PARTS for part in candidate.parts):
                continue
            key = candidate.resolve()
            if key not in seen:
                seen.add(key)
                yield candidate


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_sqlite(path):
    if not path.exists():
        return "missing"
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return connection.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned archive contents and size without creating a backup.",
    )
    parser.add_argument(
        "--skip-sqlite-check",
        action="store_true",
        help="Skip SQLite quick_check when only estimating archive contents.",
    )
    parser.add_argument(
        "--trust-existing-sqlite",
        action="store_true",
        help="Create the archive without running PRAGMA quick_check on very large SQLite files. Use only after a separate migration/count audit.",
    )
    parser.add_argument(
        "--fast-large-files",
        action="store_true",
        help="Do not hash files larger than --large-file-threshold-mb during archive creation.",
    )
    parser.add_argument(
        "--skip-large-state",
        action="store_true",
        help="Do not include the large SQLite database or local model weights; record their existing paths in the manifest.",
    )
    parser.add_argument("--large-file-threshold-mb", type=int, default=512)
    args = parser.parse_args()
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output = Path(args.output) if args.output else ROOT / "backups" / f"restore-point-{stamp}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    files = list(iter_files(skip_large_state=args.skip_large_state))
    database = ROOT / "backend" / "curriculum_kag.db"
    database_check = (
        "external_existing"
        if args.skip_large_state
        else "trusted_existing" if args.trust_existing_sqlite else "skipped" if args.skip_sqlite_check else check_sqlite(database)
    )
    if database_check not in {"ok", "external_existing"}:
        if args.trust_existing_sqlite:
            database_check = "trusted_existing"
        elif args.skip_sqlite_check and args.dry_run:
            database_check = "skipped"
        else:
            raise RuntimeError(f"SQLite quick_check failed: {database_check}")

    total_size = sum(path.stat().st_size for path in files)
    if args.dry_run:
        largest = sorted(files, key=lambda path: path.stat().st_size, reverse=True)[:12]
        print(json.dumps({
            "status": "dry_run",
            "output": str(output),
            "files": len(files),
            "uncompressed_bytes": total_size,
            "uncompressed_gb": round(total_size / 1024**3, 2),
            "sqlite_quick_check": database_check,
            "largest_files": [
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "size_gb": round(path.stat().st_size / 1024**3, 3),
                }
                for path in largest
            ],
        }, ensure_ascii=False, indent=2), flush=True)
        return

    manifest_files = []
    total_size = 0
    with zipfile.ZipFile(output, "w", allowZip64=True) as archive:
        for index, path in enumerate(files, 1):
            relative = path.relative_to(ROOT).as_posix()
            size = path.stat().st_size
            # Model weights and SQLite are already dense; storing them is much faster.
            compression = zipfile.ZIP_STORED if size > 50 * 1024 * 1024 else zipfile.ZIP_DEFLATED
            archive.write(path, relative, compress_type=compression, compresslevel=6 if compression == zipfile.ZIP_DEFLATED else None)
            large_file = size > args.large_file_threshold_mb * 1024 * 1024
            manifest_files.append({
                "path": relative,
                "size": size,
                "sha256": None if args.fast_large_files and large_file else sha256(path),
                "sha256_status": "skipped_large_file" if args.fast_large_files and large_file else "ok",
            })
            total_size += size
            if index % 100 == 0:
                print(json.dumps({"files_done": index, "files_total": len(files)}), flush=True)
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "project_root": str(ROOT),
            "purpose": "Rollback code, configuration, SQLite database, and EPVO SBERT 40k model",
            "epvo_dataset_included": False,
            "large_state_included": not args.skip_large_state,
            "sqlite_database_location": "backend/curriculum_kag.db",
            "sbert_40k_model_location": "backend/models/epvo-sbert-finetuned-40k",
            "epvo_archive_location": "outputs/epvo_export_20260705/EPVO_Полный_CSV_архив.zip",
            "sqlite_quick_check": database_check,
            "file_count": len(manifest_files),
            "uncompressed_bytes": total_size,
            "files": manifest_files,
        }
        archive.writestr("BACKUP_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2), compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("RESTORE_RU.txt", "Распакуйте архив в пустую папку. Перед заменой рабочего проекта остановите start.bat. Файл backend/.env содержит локальную конфигурацию и должен храниться приватно. Выгрузка ЕПВО хранится отдельно и в этот архив не включена.\n", compress_type=zipfile.ZIP_DEFLATED)
    print(json.dumps({"status": "complete", "output": str(output), "archive_bytes": output.stat().st_size, "files": len(files), "sqlite_quick_check": database_check}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
