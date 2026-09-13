"""Create a redacted, reproducible manifest for a planner acceptance run.

This script deliberately does not import the application or open a database.
The executor supplies the immutable catalogue revision produced by the data
pipeline; omitting it records ``unverified`` rather than inventing a data
fingerprint from row counts or a connection string.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[2]
SAFE_ENVIRONMENT_KEYS = (
    "ENABLE_SBERT", "SBERT_DEVICE", "EMBEDDING_MODEL_NAME", "EMBEDDING_DIMENSION",
    "SBERT_BATCH_SIZE", "EPVO_RANKER_WEIGHT", "EPVO_RANKER_DEVICE",
    "NSGA2_POPULATION", "NSGA2_GENERATIONS", "COVERAGE_THRESHOLD",
    "SIMILARITY_THRESHOLD", "PYDANTIC_AI_ENABLED", "PYDANTIC_AI_MODEL_NAME",
    "PYDANTIC_AI_RETRIES", "LLM_MODEL_NAME", "ASYNC_BUILDS",
)
MANIFEST_FILES = (
    "backend/requirements.lock",
    "backend/app/config.py",
    "backend/app/planner/goso_ruleset.py",
    "backend/data/goso/goso-ruleset-2026.json",
    "backend/app/kag/embedding_service.py",
)


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command_output(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=10, check=False)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def atomic_write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def build_manifest(*, seed: int, catalog_revision: str | None, run_kind: str) -> dict:
    tracked = {relative: file_sha256(ROOT / relative) for relative in MANIFEST_FILES}
    dirty = command_output(["git", "status", "--porcelain=v1"]) or ""
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_kind": run_kind,
        "seed": seed,
        "source": {
            "git_head": command_output(["git", "rev-parse", "HEAD"]),
            "dirty_worktree": bool(dirty),
            "dirty_worktree_sha256": hashlib.sha256(dirty.encode("utf-8")).hexdigest(),
            "files_sha256": tracked,
        },
        "catalog": (
            {"status": "verified", "revision": catalog_revision}
            if catalog_revision else
            {"status": "unverified", "reason": "catalog revision was not supplied by the data pipeline"}
        ),
        "runtime": {
            "python": sys.version,
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "safe_configuration": {
            key: os.environ.get(key)
            for key in SAFE_ENVIRONMENT_KEYS
            if os.environ.get(key) is not None
        },
        "redaction": {
            "excluded": ["DATABASE_URL", "LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LLM_BASE_URL"],
            "note": "Manifest intentionally contains no connection strings, credentials or API endpoints.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=20260908)
    parser.add_argument("--catalog-revision")
    parser.add_argument("--run-kind", default="planner-acceptance")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(seed=args.seed, catalog_revision=args.catalog_revision, run_kind=args.run_kind)
    atomic_write_json(output, manifest)
    print(json.dumps({"output": str(output), "catalog": manifest["catalog"], "git_head": manifest["source"]["git_head"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
