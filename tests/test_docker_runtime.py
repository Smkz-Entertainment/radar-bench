from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from radar_bench.execution.docker_runtime import (
    MAX_DOCKER_INFO_BYTES,
    inspect_docker_runtime,
)


class DockerRuntimeTests(unittest.TestCase):
    def test_accepts_linux_x86_engine_independent_of_host_os(self) -> None:
        runner = Mock(
            return_value=subprocess.CompletedProcess(
                ["docker"],
                0,
                json.dumps({"OSType": "linux", "Architecture": "x86_64"}).encode(),
                b"",
            )
        )

        result = inspect_docker_runtime(runner=runner, executable="docker")

        self.assertTrue(result.available)
        self.assertTrue(result.supported)
        self.assertEqual(result.engine_os, "linux")
        self.assertEqual(result.engine_architecture, "x86_64")
        self.assertIsNone(result.reason)
        runner.assert_called_once_with(
            ["docker", "info", "--format", "{{json .}}"],
            capture_output=True,
            check=False,
            shell=False,
            timeout=10,
        )

    def test_rejects_non_linux_engine_without_host_inference(self) -> None:
        runner = Mock(
            return_value=subprocess.CompletedProcess(
                ["docker"],
                0,
                json.dumps({"OSType": "windows", "Architecture": "x86_64"}).encode(),
                b"",
            )
        )

        result = inspect_docker_runtime(runner=runner, executable="docker")

        self.assertTrue(result.available)
        self.assertFalse(result.supported)
        self.assertEqual(result.reason, "PLATFORM_UNAVAILABLE")

    def test_fails_closed_when_docker_is_missing_or_unusable(self) -> None:
        with patch("radar_bench.execution.docker_runtime.shutil.which", return_value=None):
            missing = inspect_docker_runtime()
        self.assertEqual(missing.reason, "RUNTIME_UNAVAILABLE")

        failing = inspect_docker_runtime(
            runner=Mock(
                return_value=subprocess.CompletedProcess(
                    ["docker"], 1, b"", b"daemon unavailable"
                )
            ),
            executable="docker",
        )
        self.assertEqual(failing.reason, "DOCKER_INFO_UNAVAILABLE")

    def test_rejects_malformed_or_oversized_info(self) -> None:
        malformed = inspect_docker_runtime(
            runner=Mock(
                return_value=subprocess.CompletedProcess(
                    ["docker"], 0, b"not-json", b""
                )
            ),
            executable="docker",
        )
        self.assertEqual(malformed.reason, "DOCKER_INFO_INVALID")

        oversized = inspect_docker_runtime(
            runner=Mock(
                return_value=subprocess.CompletedProcess(
                    ["docker"], 0, b"x" * (MAX_DOCKER_INFO_BYTES + 1), b""
                )
            ),
            executable="docker",
        )
        self.assertEqual(oversized.reason, "DOCKER_INFO_TOO_LARGE")


if __name__ == "__main__":
    unittest.main()
