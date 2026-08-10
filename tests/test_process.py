from __future__ import annotations

import sys

import pytest

from radar_bench.execution.process import run_bounded


def test_bounded_process_returns_digest_and_payload() -> None:
    result = run_bounded(
        [sys.executable, "-c", "print('ok')"],
        timeout=2,
        max_output_bytes=1024,
    )
    assert result.returncode == 0
    assert result.output_bytes > 0
    assert result.output_digest.startswith("sha256:")
    assert result.payload.replace(b"\r\n", b"\n") == b"ok\n"


def test_bounded_process_stops_output_flood() -> None:
    result = run_bounded(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000000)"],
        timeout=2,
        max_output_bytes=1024,
    )
    assert result.output_limit_exceeded is True
    assert result.output_bytes > 1024
    assert len(result.payload) <= 1024


def test_bounded_process_stops_timeout() -> None:
    result = run_bounded(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout=0.1,
        max_output_bytes=1024,
    )
    assert result.timed_out is True
    assert result.returncode is not None


def test_bounded_process_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError):
        run_bounded([], timeout=1, max_output_bytes=1)
    with pytest.raises(ValueError):
        run_bounded([sys.executable, "-c", "pass"], timeout=0, max_output_bytes=1)
    with pytest.raises(OSError):
        run_bounded(["radar-bench-command-that-does-not-exist"], timeout=1, max_output_bytes=1)


def test_bounded_process_writes_bounded_input() -> None:
    result = run_bounded(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
        timeout=2,
        max_output_bytes=1024,
        input_data=b"input",
    )
    assert result.returncode == 0
    assert result.payload.replace(b"\r\n", b"\n") == b"input"


def test_terminate_tree_posix_and_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import radar_bench.execution.process as process_module

    class FakeProcess:
        pid = 123

    monkeypatch.setattr(process_module.os, "name", "posix")
    monkeypatch.setattr(process_module.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(process_module.os, "killpg", lambda *_args: None, raising=False)
    assert process_module._terminate_tree(FakeProcess()) is None
    def fail(*_args: object) -> None:
        raise OSError("no process")
    monkeypatch.setattr(process_module.os, "killpg", fail, raising=False)
    assert process_module._terminate_tree(FakeProcess()) == "OSError"
