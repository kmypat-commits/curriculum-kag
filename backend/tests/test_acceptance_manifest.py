import os

from scripts.create_acceptance_manifest import SAFE_ENVIRONMENT_KEYS, build_manifest


def test_manifest_is_explicit_when_catalog_revision_is_unverified(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "must-not-appear")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@example.test/db")
    monkeypatch.setenv("ENABLE_SBERT", "true")

    manifest = build_manifest(seed=7, catalog_revision=None, run_kind="contract")

    assert manifest["catalog"]["status"] == "unverified"
    assert manifest["seed"] == 7
    assert manifest["safe_configuration"] == {"ENABLE_SBERT": "true"}
    rendered = str(manifest)
    assert "must-not-appear" not in rendered
    assert "secret@example.test" not in rendered


def test_manifest_records_an_explicit_catalog_revision(monkeypatch):
    for key in SAFE_ENVIRONMENT_KEYS:
        monkeypatch.delenv(key, raising=False)

    manifest = build_manifest(seed=9, catalog_revision="catalog-sha256:abc", run_kind="runtime")

    assert manifest["catalog"] == {"status": "verified", "revision": "catalog-sha256:abc"}
    assert manifest["run_kind"] == "runtime"
    assert manifest["source"]["files_sha256"]["backend/app/config.py"]
