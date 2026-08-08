"""Integrity checks for generated snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from radar_bench.snapshots.leakage import scan_leakage


def check_snapshot(case_path: Path, snapshot_path: Path) -> list[str]:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    input_payload = json.loads(
        (snapshot_path / "input" / "snapshot.json").read_text(encoding="utf-8")
    )
    errors = scan_leakage(case, input_payload)
    if (snapshot_path / "gold").resolve() == (snapshot_path / "input").resolve():
        errors.append("gold and input directories must be separate")
    return errors
