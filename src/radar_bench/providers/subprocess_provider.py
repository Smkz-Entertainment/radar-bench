"""Safe JSON stdin/stdout subprocess provider using argument arrays."""

from __future__ import annotations

import json
from typing import Any

from radar_bench.errors import SecurityError
from radar_bench.execution.process import run_bounded

MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 10 * 1024 * 1024


class SubprocessProvider:
    name = "local_model"

    def __init__(self, argv: list[str], *, timeout: float = 60.0) -> None:
        if not argv or any(
            value in {"-c", "-Command", "/c", "-EncodedCommand"} for value in argv
        ):
            raise SecurityError(
                "subprocess provider requires a non-shell command array"
            )
        if timeout <= 0:
            raise SecurityError("subprocess provider timeout must be positive")
        self.argv, self.timeout = list(argv), timeout

    def predict(self, packet: dict[str, Any]) -> dict[str, Any]:
        serialized = json.dumps(packet)
        if len(serialized.encode("utf-8")) > MAX_INPUT_BYTES:
            raise SecurityError("subprocess provider input exceeds the size limit")
        completed = run_bounded(
            self.argv,
            timeout=self.timeout,
            max_output_bytes=MAX_OUTPUT_BYTES,
            input_data=serialized.encode("utf-8"),
        )
        if completed.timed_out:
            raise TimeoutError("provider timed out")
        if completed.output_limit_exceeded:
            raise SecurityError("subprocess provider output exceeds the size limit")
        if completed.returncode != 0:
            raise RuntimeError(f"provider exited with {completed.returncode}")
        value = json.loads(completed.payload.decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("provider output is not an object")
        return value
