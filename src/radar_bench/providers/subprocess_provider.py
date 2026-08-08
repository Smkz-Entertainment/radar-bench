"""Safe JSON stdin/stdout subprocess provider using argument arrays."""

from __future__ import annotations

import json
import subprocess  # nosec B404 - typed argv, shell=False, no inherited shell
from typing import Any

from radar_bench.errors import SecurityError


class SubprocessProvider:
    name = "local_model"

    def __init__(self, argv: list[str], *, timeout: float = 60.0) -> None:
        if not argv or any(
            value in {"-c", "-Command", "/c", "-EncodedCommand"} for value in argv
        ):
            raise SecurityError(
                "subprocess provider requires a non-shell command array"
            )
        self.argv, self.timeout = list(argv), timeout

    def predict(self, packet: dict[str, Any]) -> dict[str, Any]:
        completed = subprocess.run(  # nosec B603 - command policy rejects shell construction
            self.argv,
            input=json.dumps(packet),
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"provider exited with {completed.returncode}")
        value = json.loads(completed.stdout)
        if not isinstance(value, dict):
            raise TypeError("provider output is not an object")
        return value
