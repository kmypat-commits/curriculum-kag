import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.migrate_sqlite_to_postgres import file_sha256, validate_orphan_policy
from scripts.accept_sqlite_postgres_migration import file_sha256 as acceptance_file_sha256
from scripts.accept_sqlite_postgres_migration import source_sqlite_url
from scripts.compare_sqlite_postgres_counts import validate_sqlite_source
from scripts.compare_sqlite_postgres_counts import _canonical
from scripts.compare_sqlite_postgres_counts import _digest_rows_for_table
from scripts.build_sqlite_fk_discard_manifest import ORPHAN_ACTIONS


def test_known_orphan_derived_tables_have_explicit_discard_policy():
    assert {table: ORPHAN_ACTIONS[table] for table in (
        "embeddings", "match_scores", "match_feedback", "bridge_modules",
    )} == {
        "embeddings": "discard_and_regenerate",
        "match_scores": "discard_and_regenerate",
        "match_feedback": "discard_and_regenerate",
        "bridge_modules": "discard_and_regenerate",
    }


def _dirty_sqlite(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE parent (id INTEGER PRIMARY KEY);"
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER, "
            "FOREIGN KEY(parent_id) REFERENCES parent(id));"
            "PRAGMA foreign_keys=OFF;"
            "INSERT INTO child(id, parent_id) VALUES (1, 999);"
        )


def test_migration_rejects_orphans_without_manifest(tmp_path):
    source = tmp_path / "dirty.db"
    _dirty_sqlite(source)

    with pytest.raises(SystemExit, match="FK violations"):
        validate_orphan_policy(f"sqlite:///{source.as_posix()}", None)


def test_migration_rejects_review_required_manifest(tmp_path):
    source = tmp_path / "dirty.db"
    _dirty_sqlite(source)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({
            "source_sha256": file_sha256(source),
            "total_violations": 1,
            "policy": {"mode": "review_required", "destructive_action_performed": False},
            "violations_by_child_table": {"child": 1},
            "required_action_by_child_table": {"child": "repair_or_review_before_cutover"},
        }),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="repair/review"):
        validate_orphan_policy(f"sqlite:///{source.as_posix()}", manifest)


def test_migration_rejects_manifest_without_review_only_policy(tmp_path):
    source = tmp_path / "dirty.db"
    _dirty_sqlite(source)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "source_sha256": file_sha256(source),
        "total_violations": 1,
        "violations_by_child_table": {"child": 1},
        "required_action_by_child_table": {"child": "discard_and_regenerate"},
    }), encoding="utf-8")

    with pytest.raises(SystemExit, match="review_required"):
        validate_orphan_policy(f"sqlite:///{source.as_posix()}", manifest)


def test_migration_rejects_manifest_with_wrong_table_counts(tmp_path):
    source = tmp_path / "dirty.db"
    _dirty_sqlite(source)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "source_sha256": file_sha256(source),
        "total_violations": 1,
        "policy": {"mode": "review_required", "destructive_action_performed": False},
        "violations_by_child_table": {"other": 1},
        "required_action_by_child_table": {"child": "discard_and_regenerate"},
    }), encoding="utf-8")

    with pytest.raises(SystemExit, match="violations_by_child_table"):
        validate_orphan_policy(f"sqlite:///{source.as_posix()}", manifest)


def test_acceptance_normalizes_relative_source_against_repository_root():
    url = source_sqlite_url(Path("backend/curriculum_kag.db"))
    assert url.startswith("sqlite:///")
    assert url.endswith("/backend/curriculum_kag.db")


def test_acceptance_source_hash_changes_when_snapshot_source_changes(tmp_path):
    source = tmp_path / "source.db"
    source.write_bytes(b"version-one")
    first = acceptance_file_sha256(source)
    source.write_bytes(b"version-two")
    assert acceptance_file_sha256(source) != first


def test_compare_rejects_empty_sqlite_source(tmp_path):
    source = tmp_path / "empty.db"
    source.touch()

    with pytest.raises(SystemExit, match="empty"):
        validate_sqlite_source(source, ["users"])


def test_compare_rejects_incompatible_sqlite_schema(tmp_path):
    source = tmp_path / "wrong.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")

    with pytest.raises(SystemExit, match="missing expected tables"):
        validate_sqlite_source(source, ["users"])


def test_hash_canonicalizer_normalizes_python_datetimes_like_sqlite_iso_strings():
    sqlite_text = "2026-09-08T10:00:00"
    postgres_datetime = datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc)
    assert _canonical(sqlite_text) == _canonical(postgres_datetime)


def test_vector_digest_uses_postgres_pgvector_precision_for_sqlite_json():
    columns = ["id", "chunk_id", "vector", "model_version"]
    sqlite_rows = [(1, 2, "[-0.4472135954999579,0.24253562503633297]", "model")]
    postgres_rows = [(1, 2, "[-0.4472136,0.2425356]", "model")]
    assert _digest_rows_for_table(sqlite_rows, "embeddings", columns) == _digest_rows_for_table(
        postgres_rows, "embeddings", columns
    )
