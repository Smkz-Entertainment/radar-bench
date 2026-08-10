"""Provider protocol and inference packet boundary."""

from __future__ import annotations

from typing import Any, Protocol, cast


class Provider(Protocol):
    name: str

    def predict(self, packet: dict[str, Any]) -> dict[str, Any]: ...


def inference_packet(
    snapshot_path: Any, *, allowed_root: Any = None
) -> dict[str, Any]:
    import json
    from pathlib import Path

    path = Path(snapshot_path).resolve()
    if "gold" in path.parts:
        raise ValueError("inference packets cannot be loaded from gold paths")
    if allowed_root is not None:
        root = Path(allowed_root).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("inference packet is outside the candidate boundary") from exc
    return cast(
        dict[str, Any],
        json.loads((path / "input" / "snapshot.json").read_text(encoding="utf-8")),
    )
