"""Safe lifecycle helpers for long-running EPVO smoke processes."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

from fastapi import HTTPException

EXTERNAL_SMOKE_MAX_RUNTIME_SECONDS = 6 * 60 * 60


def external_process_alive(pid: object) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) calls TerminateProcess on Windows. A zero-time
        # wait on a SYNCHRONIZE-only handle observes without sending signals.
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        if value > 0xFFFFFFFF:
            return False
        handle = kernel.OpenProcess(0x00100000, False, value)  # SYNCHRONIZE
        if not handle:
            # Only ERROR_INVALID_PARAMETER establishes absence. Access denied
            # and other observation failures must not authorise a duplicate run.
            return ctypes.get_last_error() != 87
        try:
            return kernel.WaitForSingleObject(handle, 0) != 0  # WAIT_OBJECT_0 = exited
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def reconcile_external_smoke_status(status: dict, status_file: Path, metrics_path: Path,
                                   *, is_alive=None, max_runtime_seconds=EXTERNAL_SMOKE_MAX_RUNTIME_SECONDS) -> dict:
    """Convert an orphaned or overlong process record into a terminal state."""
    if status.get("state") != "running" or metrics_path.exists():
        return status
    started_at = status.get("started_at")
    age_seconds = None
    if started_at:
        try:
            started = time.mktime(time.strptime(str(started_at), "%Y-%m-%dT%H:%M:%SZ"))
            age_seconds = max(0, time.time() - started)
        except (TypeError, ValueError, OverflowError):
            age_seconds = None
    if (is_alive or external_process_alive)(status.get("pid")) and (
        age_seconds is None or age_seconds <= max_runtime_seconds
    ):
        return status
    result = dict(status)
    result.update({
        "state": "failed",
        "stale": True,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "returncode": None,
        "message": (
            "Smoke process exceeded the maximum runtime and was marked failed. Check the logs before starting a new run."
            if age_seconds is not None and age_seconds > max_runtime_seconds
            else "Smoke process is no longer available; run was marked failed. Start a new run explicitly after checking the logs."
        ),
    })
    try:
        status_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return result


def cancel_external_smoke(
    status_file: Path,
    metrics_path: Path,
    expected_script: str,
    *,
    is_alive=external_process_alive,
    reconcile_status=reconcile_external_smoke_status,
) -> dict:
    """Terminate only a recorded process whose command identity is verified."""
    if not status_file.exists():
        return {"state": "idle", "cancelled": False}
    try:
        status = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Smoke status file is unreadable") from exc
    status = reconcile_status(status, status_file, metrics_path)
    if status.get("state") != "running":
        return {"state": status.get("state", "idle"), "cancelled": False}
    command_text = " ".join(str(part) for part in (status.get("command") or []))
    if expected_script not in command_text:
        raise HTTPException(status_code=409, detail="Smoke PID identity cannot be verified")
    pid = status.get("pid")
    if not is_alive(pid):
        return reconcile_status(status, status_file, metrics_path)
    try:
        os.kill(int(pid), signal.SIGTERM)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Smoke process could not be terminated safely") from exc
    result = dict(status)
    result.update({
        "state": "cancelled", "cancelled": True, "returncode": -int(signal.SIGTERM),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "message": "Smoke run was cancelled by an administrator.",
    })
    status_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
