"""Capability detection for the Docker engine used by executable suites.

The benchmark contract is about the container engine, not the operating system
that launches the Docker client.  Docker Desktop on Windows and macOS can
provide the same Linux/x86-64 engine used by the canonical suite.  This module
detects that capability without changing the suite's Linux, architecture, or
network-isolation requirements.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 - fixed Docker argv and shell disabled
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from radar_bench.execution.process import run_bounded

DOCKER_INFO_TIMEOUT_SECONDS = 10
MAX_DOCKER_INFO_BYTES = 1024 * 1024
SUPPORTED_ENGINE_OS = "linux"
SUPPORTED_ENGINE_ARCHITECTURES = frozenset({"x86_64", "amd64"})

Runner = Callable[..., subprocess.CompletedProcess[bytes]]


@dataclass(frozen=True)
class DockerRuntime:
    """A redacted, machine-readable Docker engine capability result."""

    available: bool
    supported: bool
    engine_os: str | None
    engine_architecture: str | None
    reason: str | None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe result without exposing local executable paths."""

        return {
            "available": self.available,
            "supported": self.supported,
            "engine_os": self.engine_os,
            "engine_architecture": self.engine_architecture,
            "reason": self.reason,
        }


def _normalise(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower()


def inspect_docker_runtime(
    *,
    runner: Runner = subprocess.run,
    executable: str | None = None,
) -> DockerRuntime:
    """Inspect Docker's server engine, failing closed on incomplete metadata.

    ``docker info`` is deliberately queried instead of inferring capability
    from ``sys.platform``.  The command is fixed, shell-free, time-bounded, and
    its output is never returned to callers or stored in release evidence.
    """

    docker = executable or shutil.which("docker")
    if not docker:
        return DockerRuntime(
            available=False,
            supported=False,
            engine_os=None,
            engine_architecture=None,
            reason="RUNTIME_UNAVAILABLE",
        )

    argv = [docker, "info", "--format", "{{json .}}"]
    try:
        if runner is subprocess.run:
            bounded = run_bounded(
                argv,
                timeout=DOCKER_INFO_TIMEOUT_SECONDS,
                max_output_bytes=MAX_DOCKER_INFO_BYTES,
            )
            if bounded.timed_out or bounded.cleanup_error:
                return DockerRuntime(
                    available=False,
                    supported=False,
                    engine_os=None,
                    engine_architecture=None,
                    reason="DOCKER_INFO_UNAVAILABLE",
                )
            if bounded.output_limit_exceeded:
                return DockerRuntime(
                    available=True,
                    supported=False,
                    engine_os=None,
                    engine_architecture=None,
                    reason="DOCKER_INFO_TOO_LARGE",
                )
            returncode = bounded.returncode
            output = bounded.payload
        else:
            completed = runner(
                argv,
                capture_output=True,
                check=False,
                shell=False,
                timeout=DOCKER_INFO_TIMEOUT_SECONDS,
            )
            returncode = completed.returncode
            output = completed.stdout or b""
    except (OSError, subprocess.TimeoutExpired):
        return DockerRuntime(
            available=False,
            supported=False,
            engine_os=None,
            engine_architecture=None,
            reason="DOCKER_INFO_UNAVAILABLE",
        )

    if len(output) > MAX_DOCKER_INFO_BYTES:
        return DockerRuntime(
            available=True,
            supported=False,
            engine_os=None,
            engine_architecture=None,
            reason="DOCKER_INFO_TOO_LARGE",
        )
    if returncode != 0:
        return DockerRuntime(
            available=True,
            supported=False,
            engine_os=None,
            engine_architecture=None,
            reason="DOCKER_INFO_UNAVAILABLE",
        )

    try:
        info = json.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return DockerRuntime(
            available=True,
            supported=False,
            engine_os=None,
            engine_architecture=None,
            reason="DOCKER_INFO_INVALID",
        )
    if not isinstance(info, dict):
        return DockerRuntime(
            available=True,
            supported=False,
            engine_os=None,
            engine_architecture=None,
            reason="DOCKER_INFO_INVALID",
        )

    engine_os = _normalise(info.get("OSType"))
    engine_architecture = _normalise(info.get("Architecture"))
    supported = (
        engine_os == SUPPORTED_ENGINE_OS
        and engine_architecture in SUPPORTED_ENGINE_ARCHITECTURES
    )
    return DockerRuntime(
        available=True,
        supported=supported,
        engine_os=engine_os,
        engine_architecture=engine_architecture,
        reason=None if supported else "PLATFORM_UNAVAILABLE",
    )
