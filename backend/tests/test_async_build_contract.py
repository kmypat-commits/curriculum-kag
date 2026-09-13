import json
import os
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.api.planner_build_contracts import (
    normalize_requested_variants,
    partition_publishable_variants,
)


def test_default_variant_request_builds_only_a_but_all_remains_explicit():
    assert normalize_requested_variants(None) == ["A"]
    assert normalize_requested_variants("") == ["A"]
    assert normalize_requested_variants("all") == ["A", "B", "C"]


def test_valid_a_is_publishable_when_an_explicit_comparison_variant_fails():
    published, rejected = partition_publishable_variants(
        {"A": {"plan_id": 10}, "B": {"plan_id": 11}, "C": {"plan_id": 12}},
        [{"variant": "B", "hard": 1}],
    )

    assert published == {"A": {"plan_id": 10}, "C": {"plan_id": 12}}
    assert rejected == {"B"}


def test_no_variant_is_publishable_when_each_failed_verification():
    published, rejected = partition_publishable_variants(
        {"A": {"plan_id": 10}},
        [{"variant": "A", "hard": 2}],
    )

    assert published == {}
    assert rejected == {"A"}


def test_async_build_enqueues_worker_without_recursive_spawn():
    import app.api.planner_build as module
    from app.schemas.planner import PlannerBuildRequest

    class FakeProcess:
        pid = 4242

    claims = []

    def fake_claim(version_id, **payload):
        claims.append((version_id, payload))
        return {"state": "queued", "stage": "queued", "job_id": payload["job_id"]}

    with patch.object(module.settings, "ASYNC_BUILDS", True), \
         patch.dict(os.environ, {"CURRICULUM_KAG_WORKER": ""}), \
         patch.object(module, "_get_build_status", lambda _version_id: {"state": "idle"}), \
         patch.object(module, "_claim_build_status", fake_claim), \
         patch.object(module.subprocess, "Popen", lambda *args, **kwargs: FakeProcess()):
        response = module.build_plan(
            project_version_id=77,
            payload=PlannerBuildRequest(variants=["A", "B"]),
            db=None,
            current_user=SimpleNamespace(id=12),
        )

    assert response.status_code == 202
    body = json.loads(response.body)
    assert body["state"] == "queued"
    assert body["job_id"].startswith("build-")
    assert "4242" not in body["job_id"]
    assert claims[0][0] == 77
    assert claims[0][1]["state"] == "queued"
    assert claims[0][1]["requested_variants"] == ["A", "B"]


def test_idempotency_replays_terminal_job_without_spawning_worker():
    import app.api.planner_build as module
    from app.schemas.planner import PlannerBuildRequest

    status = {
        "state": "rejected", "job_id": "build-existing", "idempotency_key": "same-key",
        "request_hash": module._build_request_hash(77, ["A"]),
    }
    with patch.object(module.settings, "ASYNC_BUILDS", True), \
         patch.dict(os.environ, {"CURRICULUM_KAG_WORKER": ""}), \
         patch.object(module, "_load_program_spec_for_command", return_value=({}, "spec")), \
         patch.object(module, "_get_build_status", return_value=status), \
         patch.object(module.subprocess, "Popen") as spawn:
        response = module.build_plan(
            project_version_id=77,
            payload=PlannerBuildRequest(variants=["A"]),
            db=None,
            current_user=SimpleNamespace(id=12),
            idempotency_key="same-key",
        )

    assert response.status_code == 200
    assert json.loads(response.body)["idempotent_replay"] is True
    spawn.assert_not_called()


def test_retry_build_rejects_live_attempts_without_touching_the_worker():
    import app.api.planner_build as module

    from fastapi import HTTPException
    from app.schemas.planner import PlannerBuildRequest

    with patch.object(module, "_get_build_status", lambda _version_id: {"state": "running"}):
        try:
            module.retry_build(
                project_version_id=77,
                payload=PlannerBuildRequest(variants=["A"]),
                db=None,
                current_user=SimpleNamespace(id=12),
            )
        except HTTPException as error:
            assert error.status_code == 409
            assert "выполняется" in str(error.detail)
        else:
            raise AssertionError("Retry must not interrupt a live build")


def test_retry_build_accepts_terminal_infeasible_result():
    import app.api.planner_build as module
    from app.schemas.planner import PlannerBuildRequest

    expected = {"state": "queued", "job_id": "retry-job"}
    with patch.object(module, "_get_build_status", lambda _version_id: {"state": "rejected"}), \
         patch.object(module, "build_plan", return_value=expected) as build:
        result = module.retry_build(
            project_version_id=821,
            payload=PlannerBuildRequest(variants=["A", "B", "C"]),
            db=None,
            current_user=SimpleNamespace(id=12),
        )

    assert result == expected
    build.assert_called_once()


def test_cancel_build_terminates_queued_job_without_waiting_for_worker():
    import app.api.planner_build as module

    with patch.object(module, "_get_build_status", lambda _version_id: {"state": "queued"}), \
         patch.object(module, "_request_build_cancel", lambda _version_id: {"state": "cancelled", "updated_at": "now"}):
        result = module.cancel_build(
            project_version_id=77,
            db=None,
            current_user=SimpleNamespace(id=12),
        )

    assert result == {"state": "cancelled", "cancelled": True, "updated_at": "now"}


def test_worker_normalizes_null_variants_to_a_for_recovery():
    import importlib.util
    worker_path = Path(__file__).parents[1] / "scripts" / "run_planner_build_worker.py"
    spec = importlib.util.spec_from_file_location("planner_worker_contract", worker_path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    assert worker._normalise_requested_variants(None) == "A"
    assert worker._normalise_requested_variants(["A", "B"]) == ["A", "B"]


def test_external_smoke_status_recovers_missing_process(tmp_path):
    import app.api.epvo as module

    status_file = tmp_path / "run-status.json"
    metrics_path = tmp_path / "metrics.json"
    status = {"state": "running", "pid": 4242, "started_at": "2099-01-01T00:00:00Z"}
    status_file.write_text(json.dumps(status), encoding="utf-8")

    with patch.object(module, "_external_process_alive", return_value=False):
        result = module._reconcile_external_smoke_status(status, status_file, metrics_path)

    assert result["state"] == "failed"
    assert result["returncode"] is None
    assert "no longer available" in result["message"]
    assert json.loads(status_file.read_text(encoding="utf-8"))["state"] == "failed"


def test_external_smoke_status_does_not_duplicate_live_process(tmp_path):
    import app.api.epvo as module

    status_file = tmp_path / "run-status.json"
    metrics_path = tmp_path / "metrics.json"
    status = {"state": "running", "pid": 4242, "started_at": "2099-01-01T00:00:00Z"}

    with patch.object(module, "_external_process_alive", return_value=True):
        result = module._reconcile_external_smoke_status(status, status_file, metrics_path)

    assert result == status
    assert not status_file.exists()


def test_external_smoke_status_expires_live_process_after_max_runtime(tmp_path):
    import app.api.epvo as module

    status_file = tmp_path / "run-status.json"
    metrics_path = tmp_path / "metrics.json"
    status = {"state": "running", "pid": 4242, "started_at": "2020-01-01T00:00:00Z"}

    with patch.object(module, "_external_process_alive", return_value=True):
        result = module._reconcile_external_smoke_status(status, status_file, metrics_path)

    assert result["state"] == "failed"
    assert "maximum runtime" in result["message"]


def test_external_smoke_cancel_requires_expected_command_identity(tmp_path):
    import app.api.epvo as module
    from fastapi import HTTPException

    status_file = tmp_path / "run-status.json"
    metrics_path = tmp_path / "metrics.json"
    status_file.write_text(json.dumps({
        "state": "running", "pid": 4242, "started_at": "2099-01-01T00:00:00Z",
        "command": ["python", "unexpected.py"],
    }), encoding="utf-8")

    with patch.object(module, "_external_process_alive", return_value=True), pytest.raises(HTTPException, match="identity"):
        module._cancel_external_smoke(status_file, metrics_path, "train_epvo_gnn_pilot.py")


def test_external_smoke_cancel_marks_verified_child_cancelled(tmp_path):
    import app.api.epvo as module

    status_file = tmp_path / "run-status.json"
    metrics_path = tmp_path / "metrics.json"
    status_file.write_text(json.dumps({
        "state": "running", "pid": 4242, "started_at": "2099-01-01T00:00:00Z",
        "command": ["python", "train_epvo_gnn_pilot.py"],
    }), encoding="utf-8")

    with patch.object(module, "_external_process_alive", return_value=True), patch.object(module.os, "kill") as kill:
        result = module._cancel_external_smoke(status_file, metrics_path, "train_epvo_gnn_pilot.py")

    kill.assert_called_once()
    assert result["state"] == "cancelled"
    assert result["cancelled"] is True
