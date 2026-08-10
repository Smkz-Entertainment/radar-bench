from __future__ import annotations

import subprocess

import pytest

from radar_bench.execution.docker_runtime import inspect_docker_runtime


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
