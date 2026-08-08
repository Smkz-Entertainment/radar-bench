"""In-process deterministic provider."""

from typing import Any

from radar_bench.baseline.engine import predict, predict_v02


class DeterministicProvider:
    name = "deterministic"

    def predict(self, packet: dict[str, Any]) -> dict[str, Any]:
        return predict(packet)


class DeterministicV02Provider:
    """Versioned validation lane with confounder-aware abstention."""

    name = "deterministic"

    def predict(self, packet: dict[str, Any]) -> dict[str, Any]:
        return predict_v02(packet)
