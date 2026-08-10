from __future__ import annotations

import json
import subprocess

from radar_bench.execution.docker_runtime import inspect_docker_runtime


def test_docker_runtime_accepts_linux_x86_64() -> None:
    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            ["docker", "info"], 0, json.dumps({"OSType": "linux", "Architecture": "x86_64"}).encode(), b""
        )

    result = inspect_docker_runtime(runner=runner, executable="docker")
    assert result.supported is True
    assert result.as_dict()["engine_os"] == "linux"


def test_docker_runtime_fails_closed_on_invalid_or_large_output() -> None:
    def invalid(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(["docker", "info"], 0, b"not-json", b"")

    def large(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            ["docker", "info"], 0, b"x" * (1024 * 1024 + 1), b""
        )

    assert inspect_docker_runtime(runner=invalid, executable="docker").reason == "DOCKER_INFO_INVALID"
    assert inspect_docker_runtime(runner=large, executable="docker").reason == "DOCKER_INFO_TOO_LARGE"
