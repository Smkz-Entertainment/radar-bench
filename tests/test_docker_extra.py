from __future__ import annotations

import json
import subprocess

import pytest

import radar_bench.execution.docker_runtime as docker_runtime
from radar_bench.execution.docker_runtime import inspect_docker_runtime
from radar_bench.execution.process import BoundedCapture


def test_docker_runtime_error_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "radar_bench.execution.docker_runtime.shutil.which", lambda _name: None
    )
    assert inspect_docker_runtime().reason == "RUNTIME_UNAVAILABLE"

    def unavailable(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise OSError("missing")

    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(["docker", "info"], 1)

    def unsupported(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            ["docker", "info"], 0, b'{"OSType":"windows","Architecture":"x86_64"}', b""
        )

    assert inspect_docker_runtime(runner=unavailable, executable="docker").reason == "DOCKER_INFO_UNAVAILABLE"
    assert inspect_docker_runtime(runner=timeout, executable="docker").reason == "DOCKER_INFO_UNAVAILABLE"
    assert inspect_docker_runtime(runner=unsupported, executable="docker").reason == "PLATFORM_UNAVAILABLE"


@pytest.mark.parametrize(
    ("capture", "reason", "available"),
    [
        (
            BoundedCapture(
                returncode=None,
                output_bytes=0,
                output_digest="sha256:" + "0" * 64,
                output_limit_exceeded=False,
                timed_out=True,
                excerpt="",
                cleanup_error=None,
            ),
            "DOCKER_INFO_UNAVAILABLE",
            False,
        ),
        (
            BoundedCapture(
                returncode=0,
                output_bytes=1024 * 1024 + 1,
                output_digest="sha256:" + "0" * 64,
                output_limit_exceeded=True,
                timed_out=False,
                excerpt="",
                cleanup_error=None,
            ),
            "DOCKER_INFO_TOO_LARGE",
            True,
        ),
    ],
)
def test_docker_default_runner_uses_bounded_capture(
    monkeypatch: pytest.MonkeyPatch,
    capture: BoundedCapture,
    reason: str,
    available: bool,
) -> None:
    monkeypatch.setattr(docker_runtime.shutil, "which", lambda _name: "docker")
    monkeypatch.setattr(docker_runtime, "run_bounded", lambda *_args, **_kwargs: capture)

    result = inspect_docker_runtime()

    assert result.reason == reason
    assert result.available is available
    assert result.supported is False


def test_docker_default_runner_parses_bounded_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docker_runtime.shutil, "which", lambda _name: "docker")
    capture = BoundedCapture(
        returncode=0,
        output_bytes=64,
        output_digest="sha256:" + "0" * 64,
        output_limit_exceeded=False,
        timed_out=False,
        excerpt="",
        payload=json.dumps({"OSType": "linux", "Architecture": "amd64"}).encode(),
        cleanup_error=None,
    )
    monkeypatch.setattr(docker_runtime, "run_bounded", lambda *_args, **_kwargs: capture)

    result = inspect_docker_runtime()

    assert result.supported is True
    assert result.engine_architecture == "amd64"
