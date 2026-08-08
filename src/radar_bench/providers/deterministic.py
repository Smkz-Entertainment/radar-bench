"""In-process deterministic provider."""

from typing import Any

from radar_bench.baseline.engine import predict


class DeterministicProvider:
    name = "deterministic"

    def predict(self, packet: dict[str, Any]) -> dict[str, Any]:
        return predict(packet)
