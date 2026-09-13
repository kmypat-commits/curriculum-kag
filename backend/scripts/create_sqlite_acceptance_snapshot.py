"""Create an immutable SQLite snapshot and a manifest for migration acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    destination = args.destination.resolve()
    manifest = (args.manifest or destination.with_suffix(destination.suffix + ".manifest.json")).resolve()
    if not source.is_file():
        raise SystemExit(f"SQLite source does not exist: {source}")
    if destination.exists():
        raise SystemExit(f"Snapshot destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_hash_before = sha256(source)
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as source_db:
        with sqlite3.connect(destination) as destination_db:
            source_db.backup(destination_db, pages=1000, sleep=0.05)
            destination_db.execute("PRAGMA journal_mode=DELETE")
            destination_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            destination_db.commit()
    source_hash_after = sha256(source)
    if source_hash_before != source_hash_after:
        destination.unlink(missing_ok=True)
        raise SystemExit("SQLite source changed during backup; snapshot discarded")
    snapshot_hash = sha256(destination)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_size": source.stat().st_size,
        "source_sha256": source_hash_after,
        "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "snapshot": str(destination),
        "snapshot_size": destination.stat().st_size,
        "snapshot_sha256": snapshot_hash,
        "immutable_input": True,
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
