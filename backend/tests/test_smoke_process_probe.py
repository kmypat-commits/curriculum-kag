"""A liveness probe must never signal a Windows process."""
import os
import subprocess
import sys

import pytest

from app.api.epvo_process_control import external_process_alive


@pytest.mark.skipif(os.name != "nt", reason="Windows native process handle contract")
def test_windows_probe_does_not_signal_and_distinguishes_exited_child(monkeypatch):
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.readline()"],
        stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW,
    )

    def forbidden_signal(*args):
        raise AssertionError("A liveness probe must not call os.kill on Windows")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "kill", forbidden_signal)
            assert external_process_alive(child.pid) is True
            assert child.poll() is None
            child.communicate(b"finish\n", timeout=10)
            assert external_process_alive(child.pid) is False
    finally:
        if child.poll() is None:
            child.communicate(b"finish\n", timeout=10)


@pytest.mark.parametrize("pid", [None, "invalid", 0, -1])
def test_invalid_process_ids_are_not_alive(pid):
    assert external_process_alive(pid) is False
