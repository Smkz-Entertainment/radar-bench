"""Resumable collection queue state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast


def load_queue(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "items": {}}
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def save_queue(path: Path, queue: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(queue, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def mark_queue_item(
    path: Path, identity: str, *, status: str, detail: str | None = None
) -> None:
    queue = load_queue(path)
    queue.setdefault("items", {})[identity] = {"status": status, "detail": detail}
    save_queue(path, queue)
