import json
import os
import time
from pathlib import Path

from scripts.audit_quality_cohort import (
    CohortRunLockedError,
    acquire_run_lock,
    attempt_output_path,
    build_cohort_cases,
    is_retryable_infrastructure_failure,
    mark_report_interrupted,
    process_identity,
    process_is_alive,
    reconcile_running_report,
    release_run_lock,
    validate_child_report,
)


def test_breadth_manifest_has_unique_contexts():
    cases = build_cohort_cases(30, "breadth")
    assert len(cases) == 30
    assert len({case["focus"] for case in cases}) == 30
    assert len({case["case_index"] for case in cases}) == 30


def test_stability_manifest_repeats_the_same_context():
    cases = build_cohort_cases(30, "stability")
    assert len({case["focus"] for case in cases}) == 1
    assert len({case["case_index"] for case in cases}) == 1


def test_cohort_runner_pid_distinguishes_live_and_missing_processes():
    assert process_is_alive(os.getpid()) is True
    assert process_is_alive(None) is False
    assert process_is_alive(2**31 - 1) is False


def test_attempt_output_is_unique_and_does_not_reuse_a_previous_report(tmp_path: Path):
    output = tmp_path / "quality.json"
    first = attempt_output_path(output, 1, "first")
    second = attempt_output_path(output, 1, "second")
    assert first != second
    assert first.parent == second.parent
    first.write_text(json.dumps({"passed": True}), encoding="utf-8")
    assert not second.exists()


def test_child_report_requires_current_exitcode_fresh_file_and_passed_payload(tmp_path: Path):
    report = tmp_path / "child.json"
    started = time.time()
    report.write_text(json.dumps({"passed": True}), encoding="utf-8")
    assert validate_child_report(report, started, 0)[0] == {"passed": True}
    assert validate_child_report(report, started, 1)[1] == "child_exit_nonzero"
    os.utime(report, (started - 10, started - 10))
    assert validate_child_report(report, started, 0)[1] == "stale_child_report"
    report.write_text("{broken", encoding="utf-8")
    assert validate_child_report(report, started, 0)[1] == "missing_or_invalid_child_report"
    report.write_text(json.dumps({"passed": False}), encoding="utf-8")
    assert validate_child_report(report, started, 0)[1] == "child_report_not_passed"


def test_retry_classifier_does_not_retry_a_content_failure_but_retries_known_infrastructure():
    assert is_retryable_infrastructure_failure(1, "credit_violations: below_target") is False
    assert is_retryable_infrastructure_failure(1, "sqlalchemy.exc.OperationalError: connection refused") is True
    assert is_retryable_infrastructure_failure(
        1,
        "Thread ...\n"
        "sentence_transformers\\sentence_transformer\\model.py in encode\n"
        "torch\\utils\\_contextlib.py in decorate_context",
    ) is True
    assert is_retryable_infrastructure_failure(0, "OperationalError") is False
    assert is_retryable_infrastructure_failure(None, "", timed_out=True) is True


def test_run_lock_rejects_a_live_owner_and_recovers_a_stale_owner(tmp_path: Path):
    path = tmp_path / "quality.json.lock"
    owner = process_identity(os.getpid()) or {"pid": os.getpid()}
    acquire_run_lock(path, owner)
    try:
        try:
            acquire_run_lock(path, owner)
        except CohortRunLockedError:
            pass
        else:
            raise AssertionError("a live owner must keep the cohort lock")
    finally:
        release_run_lock(path, owner)
    path.write_text(json.dumps({"owner": {"pid": 2**31 - 1}}), encoding="utf-8")
    acquire_run_lock(path, owner)
    release_run_lock(path, owner)
    assert not path.exists()


def test_runner_exit_marks_its_running_report_interrupted(tmp_path: Path):
    output = tmp_path / "quality.json"
    output.write_text(json.dumps({"run_id": "owned", "status": "running", "completed": 2}), encoding="utf-8")
    mark_report_interrupted(output, "owned")
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "interrupted"
    assert result["interrupt_reason"] == "runner_exited_before_terminal_summary"


def test_runner_exit_does_not_overwrite_terminal_report(tmp_path: Path):
    output = tmp_path / "quality.json"
    output.write_text(json.dumps({"run_id": "owned", "status": "passed"}), encoding="utf-8")
    mark_report_interrupted(output, "owned")
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "passed"


def test_reconcile_marks_missing_runner_as_stale(tmp_path: Path):
    output = tmp_path / "quality.json"
    output.write_text(json.dumps({
        "run_id": "old", "status": "running", "runner_pid": 2**31 - 1,
        "runner_identity": {"pid": 2**31 - 1},
    }), encoding="utf-8")
    result = reconcile_running_report(output)
    assert result["status"] == "stale"
    assert result["stale_reason"] == "runner_process_missing_or_identity_changed"


def test_reconcile_does_not_touch_terminal_report(tmp_path: Path):
    output = tmp_path / "quality.json"
    output.write_text(json.dumps({"run_id": "done", "status": "failed"}), encoding="utf-8")
    result = reconcile_running_report(output)
    assert result["status"] == "failed"
