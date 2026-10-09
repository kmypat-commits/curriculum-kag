"""Run a programme-level quality cohort using disposable control projects.

Each child audit creates one temporary programme, validates its A/B/C (or
standard) plan, and removes the project in a finally block.  No user project
or production plan is modified.  The cohort report separates level/profile
and records real-course, bridge, GOSO and hard-violation outcomes.
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import sys
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT_SCHEMA_VERSION = 2


class CohortRunLockedError(RuntimeError):
    """Raised when a different live runner owns the same output manifest."""


def atomic_write_json(path: Path, payload: dict) -> None:
    """Persist a complete JSON snapshot or leave the preceding one untouched."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def process_identity(pid: int | None) -> dict | None:
    """Return a read-only process identity suitable for a local runner lock.

    A PID alone can be reused.  Windows obtains the creation time from the
    process handle instead of sending a signal; POSIX keeps its conventional
    zero-signal probe because that is a non-destructive existence check there.
    """
    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except (OSError, PermissionError):
            return None
        return {"pid": pid}
    try:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not ctypes.windll.kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)):
                return None
            filetime = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
            return {"pid": pid, "created_at": round(filetime / 10_000_000 - 11_644_473_600, 3)}
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        return None


def process_is_alive(pid: int | None, expected_identity: dict | None = None) -> bool:
    """Return whether the recorded runner still matches its process identity."""
    actual = process_identity(pid)
    if actual is None:
        return False
    if expected_identity and expected_identity.get("created_at") is not None:
        return actual.get("created_at") == expected_identity.get("created_at")
    return True


def acquire_run_lock(path: Path, owner: dict) -> None:
    """Create one exclusive lock for an output manifest, recovering stale locks."""
    payload = {"owner": owner, "acquired_at": time.time()}
    for _ in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            existing_owner = existing.get("owner") if isinstance(existing, dict) else None
            if isinstance(existing_owner, dict) and process_is_alive(existing_owner.get("pid"), existing_owner):
                raise CohortRunLockedError(f"Cohort output is already owned by PID {existing_owner.get('pid')}")
            stale = path.with_name(f"{path.name}.stale-{uuid.uuid4().hex}")
            try:
                os.replace(path, stale)
            except FileNotFoundError:
                continue
            continue
        try:
            os.write(descriptor, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        finally:
            os.close(descriptor)
        return
    raise CohortRunLockedError("Could not acquire a stable cohort output lock")


def release_run_lock(path: Path, owner: dict) -> None:
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(existing, dict) and existing.get("owner") == owner:
        path.unlink(missing_ok=True)


def mark_report_interrupted(output: Path, run_id: str) -> None:
    """Mark an owned running report stale-safe when the runner exits."""
    try:
        if not output.exists():
            return
        current = json.loads(output.read_text(encoding="utf-8"))
        if current.get("run_id") != run_id or current.get("status") != "running":
            return
        current.update({
            "status": "interrupted",
            "interrupted_at": time.time(),
            "interrupt_reason": "runner_exited_before_terminal_summary",
        })
        atomic_write_json(output, current)
    except (OSError, json.JSONDecodeError):
        return


def reconcile_running_report(output: Path) -> dict | None:
    """Reconcile an orphaned running report using its PID/identity."""
    try:
        current = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if current.get("status") != "running":
        return current
    if process_is_alive(current.get("runner_pid"), current.get("runner_identity")):
        return current
    current.update({
        "status": "stale",
        "stale_at": time.time(),
        "stale_reason": "runner_process_missing_or_identity_changed",
    })
    atomic_write_json(output, current)
    return current


def attempt_output_path(output: Path, cohort_index: int, attempt_id: str) -> Path:
    """Never let a retry read a report produced by an earlier child attempt."""
    directory = output.parent / f"{output.stem}.attempts"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"case-{cohort_index:02d}-{attempt_id}.json"


def is_retryable_infrastructure_failure(returncode: int | None, stderr: str, timed_out: bool = False) -> bool:
    """Retry known transient infrastructure faults, never a content rejection."""
    if timed_out:
        return True
    if returncode in (None, 0):
        return False
    evidence = str(stderr or "").casefold()
    markers = (
        "operationalerror", "connection refused", "connection reset", "connection aborted",
        "server closed the connection", "could not connect", "database is unavailable",
        "temporarily unavailable", "resource temporarily unavailable",
        # Native model-loader crashes on Windows may leave only the tqdm
        # weights banner in stderr and no Python traceback. Treat this as a
        # single isolated infrastructure retry, never as a content failure.
        "loading weights:", "loading checkpoint", "access violation",
        "faulthandler", "sentence_transformers\\sentence_transformer", "torch\\utils\\_contextlib",
    )
    return any(marker in evidence for marker in markers)


def validate_child_report(path: Path, started_at: float, returncode: int | None) -> tuple[dict | None, str | None]:
    """Accept only the current child's fresh, successful, completed report."""
    if returncode != 0:
        return None, "child_exit_nonzero"
    try:
        # NTFS/Python timestamp precision can lag the clock used immediately
        # before spawning a child. The unique attempt output path is the
        # primary freshness guard; this small tolerance only avoids rejecting
        # a just-written report due to filesystem timestamp granularity.
        if path.stat().st_mtime + 2.0 < started_at:
            return None, "stale_child_report"
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "missing_or_invalid_child_report"
    if not isinstance(report, dict) or report.get("passed") is not True:
        return None, "child_report_not_passed"
    return report, None


def failed_child_details(path: Path) -> dict:
    """Retain a failed child's diagnostics without treating it as a pass."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("passed") is not False:
        return {}
    return {key: payload[key] for key in (
        "level", "profile", "status", "error", "elapsed_seconds",
        "input_sha256", "variants_are_distinct", "variants",
    ) if key in payload}


def build_cohort_cases(count: int, cohort: str, *, case_offset: int = 0) -> list[dict]:
    """Build a deterministic cohort manifest.

    ``case_offset`` lets separate batch runs form one larger non-overlapping
    breadth cohort.  It changes both the durable case identity and the focus
    text, so a 50 + 30 run cannot accidentally be presented as 80 distinct
    programmes when the second run merely repeats the first 30 inputs.
    """
    if case_offset < 0:
        raise ValueError("case_offset must not be negative")
    profiles = [
        ("bachelor", "standard"),
        ("master", "standard"),
        ("doctorate", "standard"),
        ("bachelor", "ict-medicine"),
        ("bachelor", "ict-agro"),
    ]
    focus_families = (
        "цифровая безопасность медицинских данных",
        "интеллектуальный транспорт и городская инфраструктура",
        "агротехнологии и дистанционный мониторинг",
        "финансовые информационные системы и риск-модели",
        "образовательная аналитика и цифровые платформы",
        "промышленная роботизация и цифровые двойники",
        "государственные сервисы и защита персональных данных",
        "экологический мониторинг и устойчивое развитие",
        "мультимедийные системы и доступность интерфейсов",
        "облачные вычисления и распределённые системы",
    )
    cases = [{
        "case_index": case_offset + index + 1,
        "level": profiles[(case_offset + index) % len(profiles)][0],
        "profile": profiles[(case_offset + index) % len(profiles)][1],
        "focus": (
            f"{focus_families[(case_offset + index) % len(focus_families)]} "
            f"— контрольный контекст {case_offset + index + 1}"
        ),
    } for index in range(count)]
    if cohort == "stability":
        for case in cases:
            case["case_index"] = 0
            case["focus"] = "контрольный стабильный контекст"
    return cases


def database_preflight() -> str | None:
    """Fail fast when the configured PostgreSQL target is unavailable."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        return None
    try:
        import psycopg2
        dsn = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
        connection = psycopg2.connect(dsn, connect_timeout=5)
        connection.close()
    except (ImportError, OSError, socket.error) as exc:
        return f"PostgreSQL preflight failed: {exc.__class__.__name__}"
    except Exception as exc:
        return f"PostgreSQL preflight failed: {exc.__class__.__name__}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument(
        "--case-offset", type=int, default=0,
        help="Начальный сдвиг identity входов для непересекающихся breadth-серий.",
    )
    parser.add_argument("--output", default=".runtime/quality-cohort.json")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument('--stop-on-failure', action='store_true',
                        help='Stop this strict acceptance slice on its first failed programme')
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Продолжить незавершённый прогон из существующего progress-файла.",
    )
    parser.add_argument(
        "--rerun-failed",
        action="store_true",
        help="В режиме resume повторить только ранее неуспешные кейсы.",
    )
    parser.add_argument(
        "--variants", nargs="+", choices=("A", "B", "C"), default=["A", "B", "C"],
        help="Варианты для дочернего acceptance-аудита (по умолчанию A B C).",
    )
    parser.add_argument("--cohort", choices=("stability", "breadth"), default="stability",
                        help="stability повторяет профили; breadth фиксирует уникальные входы")
    parser.add_argument("--real-input-manifest", type=Path,
                        help="Frozen, checksum-verified real-programme inputs; use 50+30 non-overlapping slices")
    args = parser.parse_args()
    if not 1 <= args.count <= 50:
        parser.error("count must be between 1 and 50")
    if args.case_offset < 0:
        parser.error("--case-offset must not be negative")
    if args.real_input_manifest:
        input_manifest = json.loads(args.real_input_manifest.read_text(encoding="utf-8"))
        prepared = input_manifest.get("prepared") or []
        if input_manifest.get("excluded_count") or input_manifest.get("prepared_count") != 80 or len(prepared) != 80:
            parser.error("real input manifest must contain 80 prepared programmes and no unresolved inputs")
        if len({str(row.get("program_id")) for row in prepared}) != 80:
            parser.error("real input manifest has duplicate programme IDs")
        if args.case_offset + args.count > len(prepared):
            parser.error("requested real-programme slice extends beyond the frozen 80 inputs")
        cases = []
        for index, entry in enumerate(prepared[args.case_offset:args.case_offset + args.count], args.case_offset + 1):
            input_path = Path(entry["input"])
            if hashlib.sha256(input_path.read_bytes()).hexdigest() != entry["sha256"]:
                parser.error(f"real programme {entry['program_id']} input SHA-256 mismatch")
            cases.append({
                "case_index": index, "program_id": str(entry["program_id"]),
                "level": entry["level"], "profile": entry["profile"],
                "input_json": str(input_path), "input_sha256": entry["canonical_sha256"],
                "input_file_sha256": entry["sha256"],
                "split": entry["split"],
            })
    else:
        cases = build_cohort_cases(args.count, args.cohort, case_offset=args.case_offset)
    if (args.cohort == "breadth" or args.real_input_manifest) and len({json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases}) != args.count:
        parser.error("breadth cohort manifest must contain unique inputs")
    manifest_bytes = json.dumps(cases, ensure_ascii=False, sort_keys=True).encode("utf-8")
    manifest = {"cohort": "real" if args.real_input_manifest else args.cohort, "cases": cases,
                "sha256": hashlib.sha256(manifest_bytes).hexdigest()}
    if args.real_input_manifest:
        manifest["source_sha256"] = input_manifest["source_sha256"]
        manifest["selection"] = input_manifest["selection"]
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    runner_identity = process_identity(os.getpid()) or {"pid": os.getpid()}
    lock_path = output.with_name(f"{output.name}.lock")
    try:
        acquire_run_lock(lock_path, runner_identity)
    except CohortRunLockedError as exc:
        print(json.dumps({"status": "locked", "reason": str(exc), "output": str(output)}, ensure_ascii=False))
        return 3
    atexit.register(release_run_lock, lock_path, runner_identity)
    atexit.register(mark_report_interrupted, output, run_id)
    preflight_error = database_preflight()
    if preflight_error:
        blocked = {
            "status": "blocked",
            "reason": preflight_error,
            "requested": args.count,
            "completed": 0,
            "passed": 0,
            "failed": 0,
            "manifest": manifest,
        }
        blocked.update({"run_id": run_id, "schema_version": REPORT_SCHEMA_VERSION})
        atomic_write_json(output, blocked)
        print(json.dumps(blocked, ensure_ascii=False))
        return 2
    reports: list[dict] = []
    recovered_from_stale = False
    if args.resume and output.exists():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
            if (
                previous.get("status") in {"running", "failed", "interrupted", "stale"}
                and previous.get("requested") == args.count
                and (previous.get("manifest") or {}).get("sha256") == manifest["sha256"]
            ):
                reports = [row for row in previous.get("reports", []) if isinstance(row, dict)]
                recovered_from_stale = (
                    previous.get("status") == "running"
                    and not process_is_alive(previous.get("runner_pid"), previous.get("runner_identity"))
                )
        except (OSError, json.JSONDecodeError):
            reports = []
    if reports:
        print(json.dumps({"status": "resuming", "completed": len(reports), "requested": args.count}, ensure_ascii=False))
    started = time.monotonic()
    pending_indexes = list(range(len(reports), args.count))
    if args.resume and args.rerun_failed:
        pending_indexes = sorted(set(
            index for index, row in enumerate(reports)
            if row.get("passed") is not True
        ) | set(pending_indexes))
    for index in pending_indexes:
        level, profile = cases[index]["level"], cases[index]["profile"]
        # Persist progress before the expensive child audit starts.  This makes
        # a stuck generation visible and leaves a resumable diagnostic record.
        atomic_write_json(output, {
            "schema_version": REPORT_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "runner_pid": os.getpid(),
            "runner_identity": runner_identity,
            "recovered_from_stale": recovered_from_stale,
            "completed": len(reports),
            "requested": args.count,
            "manifest": manifest,
            "current": {"cohort_index": index + 1, "level": level, "profile": profile,
                        "started_at": time.time(), "timeout_seconds": args.timeout},
            "reports": reports,
        })
        command = [sys.executable, str(ROOT / "backend/scripts/audit_cross_level_generation.py")]
        if args.real_input_manifest:
            command.extend(["--input-json", cases[index]["input_json"]])
        else:
            command.extend([
                "--level", level, "--profile", profile,
                "--jurisdiction", "KZ", "--focus", cases[index]["focus"],
            ])
        command.extend(["--case-index", str(cases[index]["case_index"]), "--variants", *args.variants])
        try:
            child_env = os.environ.copy()
            # Keep native BLAS/tokenizer runtimes bounded across the long
            # sequence of disposable ML audits.  This prevents thread-pool
            # exhaustion and Windows access violations without changing model
            # weights or scoring semantics.
            child_env.update({
                "OMP_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "TORCH_NUM_THREADS": "1",
                "TOKENIZERS_PARALLELISM": "false",
            })
            run_kwargs = {
                # Settings loads the backend-local `.env` by relative path.
                # Running children from the repository root silently selected
                # a different scoring profile than the real backend runtime.
                "cwd": ROOT / "backend",
                "env": child_env,
                "text": True,
                "capture_output": True,
                "timeout": args.timeout,
            }
            # A native Windows crash in the disposable child must not open a
            # modal "python.exe" dialog that blocks the whole cohort.  Retry
            # once because the audit is isolated and idempotent; a persistent
            # failure is still recorded in the cohort report.
            if os.name == "nt":
                run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            attempts = []
            report = None
            report_error = None
            for attempt_number in range(1, 3):
                attempt_id = uuid.uuid4().hex
                child_output = attempt_output_path(output, index + 1, attempt_id)
                stdout_artifact = child_output.with_suffix(".stdout.log")
                stderr_artifact = child_output.with_suffix(".stderr.log")
                started_at = time.time()
                timed_out = False
                # ``subprocess.run`` hides all progress while native model
                # inference is active.  Keep the child isolated, but poll it
                # in bounded intervals so the durable manifest proves that
                # the runner is alive and records the real elapsed time.
                popen_kwargs = {key: value for key, value in run_kwargs.items() if key not in {"timeout", "capture_output"}}
                # Do not use PIPE here: native inference can emit enough output
                # to fill a pipe while the parent is polling, deadlocking the
                # child before the heartbeat loop can observe completion.
                with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file:
                    popen_kwargs.update({"stdout": stdout_file, "stderr": stderr_file})
                    child = subprocess.Popen([*command, "--output", str(child_output)], **popen_kwargs)
                    heartbeat_started = time.monotonic()
                    while child.poll() is None:
                        elapsed = time.monotonic() - heartbeat_started
                        if elapsed >= args.timeout:
                            child.kill()
                            child.communicate()
                            timed_out = True
                            stdout_file.seek(0)
                            stderr_file.seek(0)
                            stdout = stdout_file.read()
                            stderr = stderr_file.read()
                            completed = subprocess.CompletedProcess(
                                child.args, child.returncode,
                                stdout=stdout.decode("utf-8", errors="replace"),
                                stderr=stderr.decode("utf-8", errors="replace"),
                            )
                            break
                        time.sleep(min(15.0, max(1.0, args.timeout - elapsed)))
                        atomic_write_json(output, {
                        "schema_version": REPORT_SCHEMA_VERSION,
                        "run_id": run_id,
                        "status": "running",
                        "runner_pid": os.getpid(),
                        "runner_identity": runner_identity,
                        "recovered_from_stale": recovered_from_stale,
                        "completed": len(reports),
                        "requested": args.count,
                        "manifest": manifest,
                        "current": {
                            "cohort_index": index + 1,
                            "level": level,
                            "profile": profile,
                            "started_at": started_at,
                            "timeout_seconds": args.timeout,
                            "heartbeat_at": time.time(),
                            "elapsed_seconds": round(time.monotonic() - heartbeat_started, 2),
                            "attempt": attempt_number,
                        },
                        "reports": reports,
                        })
                    if not timed_out:
                        child.communicate()
                        stdout_file.seek(0)
                        stderr_file.seek(0)
                        stdout = stdout_file.read()
                        stderr = stderr_file.read()
                        completed = subprocess.CompletedProcess(
                            child.args, child.returncode,
                            stdout=stdout.decode("utf-8", errors="replace"),
                            stderr=stderr.decode("utf-8", errors="replace"),
                        )
                    stdout_artifact.write_bytes(stdout[-1_000_000:])
                    stderr_artifact.write_bytes(stderr[-1_000_000:])
                report, report_error = validate_child_report(child_output, started_at, completed.returncode)
                if report is not None and args.real_input_manifest and report.get("input_sha256") != cases[index]["input_sha256"]:
                    report, report_error = None, "child_input_sha256_mismatch"
                attempt_record = {
                    "attempt_id": attempt_id,
                    "output": str(child_output),
                    "started_at": started_at,
                    "finished_at": time.time(),
                    "returncode": completed.returncode,
                    "report_error": report_error,
                    "stdout_artifact": str(stdout_artifact),
                    "stderr_artifact": str(stderr_artifact),
                }
                if completed.returncode != 0:
                    attempt_record["stderr_tail"] = completed.stderr[-2000:]
                attempts.append(attempt_record)
                if report is not None:
                    break
                if not is_retryable_infrastructure_failure(completed.returncode, completed.stderr, timed_out=timed_out):
                    break
            if report is None:
                report = {
                    "passed": False,
                    "error": report_error or "child_report_unavailable",
                    **failed_child_details(child_output),
                }
            report["cohort_index"] = index + 1
            report["case_index"] = cases[index]["case_index"]
            if args.real_input_manifest:
                report["program_id"] = cases[index]["program_id"]
                report["source_split"] = cases[index]["split"]
                report["expected_input_sha256"] = cases[index]["input_sha256"]
            report["process_returncode"] = attempts[-1]["returncode"]
            report["process_attempts"] = len(attempts)
            report["attempts"] = attempts
            if completed.returncode != 0:
                report["stderr_tail"] = completed.stderr[-2000:]
        except Exception as exc:  # keep the cohort moving and record the failure
            report = {"cohort_index": index + 1, "level": level, "profile": profile, "case_index": cases[index]["case_index"], "passed": False, "error": repr(exc)}
        if index < len(reports):
            reports[index] = report
        else:
            reports.append(report)
        atomic_write_json(output, {"schema_version": REPORT_SCHEMA_VERSION, "run_id": run_id, "status": "running", "runner_pid": os.getpid(), "runner_identity": runner_identity, "recovered_from_stale": recovered_from_stale, "completed": len(reports), "requested": args.count, "manifest": manifest, "reports": reports})
        if args.stop_on_failure and report.get('passed') is not True:
            break
    passed = [row for row in reports if row.get("passed") is True]
    failed = [row for row in reports if row.get("passed") is not True]
    infrastructure_failures = sum(
        1 for row in failed
        if not row.get("level") or "OperationalError" in str(row.get("stderr_tail") or row.get("error") or "")
    )
    summary = {
        # A processed cohort with failed children is not a successful
        # acceptance.  The old value ``complete`` made 0/50 infrastructure
        # failures look like a finished gate in dashboards and reports.
        "status": "passed" if len(passed) == args.count else "failed",
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_id,
        "requested": args.count,
        "completed": len(reports),
        "distinct_input_count": len({json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases}),
        "breadth_requirement_met": (args.cohort != "breadth" and not args.real_input_manifest) or len({json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases}) == args.count,
        "passed": len(passed),
        "failed": len(reports) - len(passed),
        "infrastructure_failures": infrastructure_failures,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "runner_pid": os.getpid(),
        "runner_identity": runner_identity,
        "recovered_from_stale": recovered_from_stale,
        "manifest": manifest,
        "by_level_profile": {
            f"{level}/{profile}": {
                "count": sum(1 for row in reports if row.get("level") == level and row.get("profile") == profile),
                "passed": sum(1 for row in passed if row.get("level") == level and row.get("profile") == profile),
            }
            for level, profile in {(case["level"], case["profile"]) for case in cases}
        },
        "reports": reports,
    }
    atomic_write_json(output, summary)
    print(json.dumps({k: summary[k] for k in ("status", "requested", "completed", "passed", "failed", "elapsed_seconds")}, ensure_ascii=False))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
