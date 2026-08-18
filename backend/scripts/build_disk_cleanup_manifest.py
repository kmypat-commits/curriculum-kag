"""Create a non-destructive disk-cleanup manifest for local Curriculum-KAG artefacts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".runtime"

KEEP_MODELS = {
    "paraphrase-multilingual-mpnet-base-v2": "Configured local embedding runtime model.",
    "epvo-sbert-finetuned-40k": "Best frozen classifier candidate used for reproducible benchmark reporting.",
    "epvo-sbert-mined-triplets-6k": "Configured optional second-stage ranker and reproducibility model.",
}


def size_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def entry(path: Path, action: str, reason: str) -> dict:
    total = size_bytes(path) if path.exists() else 0
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "size_bytes": total,
        "size_gb": round(total / 1024**3, 3),
        "action": action,
        "reason": reason,
        "deleted": False,
    }


def main() -> int:
    entries: list[dict] = []
    for name in ("pydantic-ai-venv", "pydantic-ai-slim-venv", "dist"):
        path = RUNTIME / name
        if path.exists():
            entries.append(entry(path, "delete_rebuildable", "Temporary local environment or generated build output."))
    for name in ("epvo-weighted-postgres", "epvo-ranking-postgres", "epvo-ranking-postgres-clean", "epvo-ranking-postgres-clean-v2", "models", "restore-source"):
        path = RUNTIME / name
        if path.exists():
            entries.append(entry(path, "archive_then_delete", "Experiment/training or recovery artefact; not required by normal application startup."))

    models = ROOT / "backend" / "models"
    for path in sorted((item for item in models.iterdir() if item.is_dir()), key=lambda item: item.name):
        if path.name in KEEP_MODELS:
            entries.append(entry(path, "keep", KEEP_MODELS[path.name]))
        elif "checkpoint" in path.name or "pilot" in path.name or "ranker" in path.name or "hardneg" in path.name:
            entries.append(entry(path, "archive_then_delete", "Intermediate or experimental training artefact, not selected by current configuration."))
        else:
            entries.append(entry(path, "review", "Model is not configured as active; retain until benchmark artefact is archived."))

    for name in ("backups_2026-08-01", "senior-refactor-20260801-215505", "experiment-results_2026-08-01", "outputs_2026-08-01"):
        path = ROOT / "archive" / name
        if path.exists():
            entries.append(entry(path, "archive_external_then_delete", "Historical archive; never read by the running application."))

    for path in (ROOT / "backups").iterdir():
        if path.is_dir():
            entries.append(entry(path, "keep_two_verified_backups", "Backups require restore verification before pruning."))
    node_modules = ROOT / "frontend" / "node_modules"
    if node_modules.exists():
        entries.append(entry(node_modules, "delete_rebuildable", "Recreated from package-lock.json by npm install."))
    venv = ROOT / "backend" / "venv"
    if venv.exists():
        entries.append(entry(venv, "keep_or_rebuild", "Required by local launch/test scripts; can be rebuilt from requirements only."))

    entries.sort(key=lambda item: item["size_bytes"], reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": "No deletion is performed by this script. archive_then_delete requires an external copy and restore check.",
        "entries": entries,
        "reclaimable_gb": round(sum(item["size_bytes"] for item in entries if item["action"] in {"delete_rebuildable", "archive_then_delete", "archive_external_then_delete"}) / 1024**3, 3),
    }
    RUNTIME.mkdir(exist_ok=True)
    (RUNTIME / "disk-cleanup-manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    candidates = [item["path"] for item in entries if item["action"] in {"delete_rebuildable", "archive_then_delete", "archive_external_then_delete"}]
    (RUNTIME / "DELETE_CANDIDATES_AFTER_ARCHIVE.txt").write_text("\n".join(candidates) + "\n", encoding="utf-8")
    print(json.dumps({"entries": len(entries), "reclaimable_gb": payload["reclaimable_gb"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
