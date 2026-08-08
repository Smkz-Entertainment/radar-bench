"""Replay provider for stored predictions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ReplayProvider:
    name = "imported"

    def __init__(self, path: Path) -> None:
        self.values: dict[str, dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                self.values[value["case_id"]] = value

    def predict(self, packet: dict[str, Any]) -> dict[str, Any]:
        return self.values.get(
            packet["case_id"], {"case_id": packet["case_id"], "verdict": "inconclusive"}
        )
