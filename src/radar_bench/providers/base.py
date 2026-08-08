"""Provider protocol and inference packet boundary."""

from __future__ import annotations

from typing import Any, Protocol, cast


class Provider(Protocol):
    name: str

    def predict(self, packet: dict[str, Any]) -> dict[str, Any]: ...


def inference_packet(snapshot_path: Any) -> dict[str, Any]:
    import json
    from pathlib import Path

    path = Path(snapshot_path).resolve()
    if "gold" in path.parts:
        raise ValueError("inference packets cannot be loaded from gold paths")
    return cast(
        dict[str, Any],
        json.loads((path / "input" / "snapshot.json").read_text(encoding="utf-8")),
    )
