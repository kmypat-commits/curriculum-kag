import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

from scripts.audit_quality_cohort import (
    CohortRunLockedError,
    acquire_run_lock,
    attempt_output_path,
    failed_child_details,
    build_cohort_cases,
    is_retryable_infrastructure_failure,
    mark_report_interrupted,
    process_identity,
    process_is_alive,
    reconcile_running_report,
    release_run_lock,
    validate_child_report,
)
from scripts.audit_cross_level_generation import has_real_cross_domain_course, load_exact_input
from app.planner.selection_evidence import snapshot_payload


def test_breadth_manifest_has_unique_contexts():
    cases = build_cohort_cases(30, "breadth")
    assert len(cases) == 30
    assert len({case["focus"] for case in cases}) == 30
    assert len({case["case_index"] for case in cases}) == 30


def test_cross_domain_evidence_is_profile_specific_and_in_one_real_course():
    agro = ["Информационные технологии в ландшафтной архитектуре"]
    medicine = ["Искусственный интеллект в здравоохранении"]
    assert has_real_cross_domain_course(agro, "ict-agro")
    assert has_real_cross_domain_course(medicine, "ict-medicine")
    assert not has_real_cross_domain_course(agro, "ict-medicine")
    assert not has_real_cross_domain_course(
        ["Анализ данных", "Растениеводство"], "ict-agro"
    )


def test_breadth_manifests_with_offsets_do_not_overlap():
    first = build_cohort_cases(50, "breadth")
    second = build_cohort_cases(30, "breadth", case_offset=50)
    assert not ({case["case_index"] for case in first} & {case["case_index"] for case in second})
    assert not ({case["focus"] for case in first} & {case["focus"] for case in second})


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


def test_failed_child_diagnostics_are_retained_without_a_false_pass(tmp_path: Path):
    output = tmp_path / "failed.json"
    output.write_text(json.dumps({
        "passed": False, "level": "doctorate", "profile": "standard",
        "variants": {"A": {"quality_violations": [{"reason": "missing_core_competency_blocks"}]}},
    }), encoding="utf-8")
    details = failed_child_details(output)
    assert details["level"] == "doctorate"
    assert details["variants"]["A"]["quality_violations"][0]["reason"] == "missing_core_competency_blocks"
    assert "passed" not in details


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


def test_exact_programme_input_requires_resolved_scope_and_preserves_outcomes(tmp_path: Path):
    source = tmp_path / "brief.json"
    source.write_text(json.dumps({
        "title": "Контрольная программа",
        "goal": "Подготовить специалиста для проверяемой задачи.",
        "domain1": "Информационно-коммуникационные технологии",
        "constraints": {
            "education_level": "bachelor", "education_area": "6B06",
            "direction_code": "6B061", "group_code": "B057",
            "instruction_language": "ru", "total_semesters": 8,
            "total_credits": 240, "max_credits_per_semester": 30,
        },
        "learning_outcomes": [{"code": "LO-REAL-1", "text": "Спроектировать проверяемую информационную систему."}],
    }, ensure_ascii=False), encoding="utf-8")
    loaded, digest = load_exact_input(str(source))
    assert len(digest) == 64
    assert loaded["learning_outcomes"][0]["code"] == "LO-REAL-1"
    assert loaded["constraints"]["group_code"] == "B057"


def test_exact_programme_input_rejects_unresolved_catalogue_scope(tmp_path: Path):
    source = tmp_path / "brief.json"
    source.write_text(json.dumps({
        "title": "Без scope", "goal": "Цель.",
        "constraints": {"education_level": "bachelor"},
        "learning_outcomes": [{"code": "LO1", "text": "Текст."}],
    }, ensure_ascii=False), encoding="utf-8")
    try:
        load_exact_input(str(source))
    except ValueError as exc:
        assert "catalogue scope" in str(exc)
    else:
        raise AssertionError("unresolved scope must not be silently accepted")


def test_selection_evidence_snapshot_uses_raw_evidence_not_ranking_boost():
    lo = SimpleNamespace(id=7, lo_code="LO1", lo_text="Проверяемый результат")
    row = SimpleNamespace(
        course_id=11,
        lo_id=7,
        score=0.99,
        evidence_json={"semantic_score": 0.42, "epvo_expert_score": 0.0, "source": "EPVO"},
        model_name="sbert",
    )
    payload = snapshot_payload([row], {7: lo})
    item = payload["11"]
    assert item["max_score"] == 0.42
    assert item["top_lo_matches"][0]["effective_score"] == 0.42
    assert item["top_lo_matches"][0]["snapshot"] is True


def test_selection_evidence_snapshot_retains_method_for_a_course_without_score():
    payload = snapshot_payload([], {}, {19: "real_epvo_credit_top_up"})

    assert payload["19"] == {
        "max_score": 0.0,
        "expert_supported": False,
        "top_lo_matches": [],
        "selection_method": "real_epvo_credit_top_up",
    }


def test_strict_cohort_stops_after_first_failed_case(tmp_path, monkeypatch):
    from scripts import audit_quality_cohort as runner
    output = tmp_path / 'strict.json'
    monkeypatch.setattr(runner.sys, 'argv', ['cohort', '--count', '2', '--variants', 'A',
                                          '--output', str(output), '--stop-on-failure'])
    monkeypatch.setattr(runner, 'database_preflight', lambda: None)
    monkeypatch.setattr(runner.atexit, 'register', lambda *args: None)
    monkeypatch.setattr(runner, 'validate_child_report', lambda *args: ({'passed': False, 'level': 'bachelor', 'profile': 'it'}, None))
    calls = []
    class Child:
        def __init__(self, args, **kwargs): self.args = args; self.returncode = 0; calls.append(args)
        def poll(self): return 0
        def communicate(self): return None, None
    monkeypatch.setattr(runner.subprocess, 'Popen', Child)
    assert runner.main() == 1
    result = json.loads(output.read_text(encoding='utf-8'))
    assert result['requested'] == 2 and result['completed'] == 1 and result['failed'] == 1
    assert len(calls) == 1
