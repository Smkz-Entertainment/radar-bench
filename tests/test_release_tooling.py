from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_release_verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "radar_bench_release_verifier", ROOT / "scripts" / "verify_release.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tracked_inventory_omits_self_reference_without_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory_path = tmp_path / "artifacts" / "v1.0.1" / "tracked-file-inventory.json"
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_text("{}\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme\n", encoding="utf-8")

    verifier = _load_release_verifier()
    monkeypatch.setattr(
        verifier,
        "_git_files",
        lambda _root: [
            "README.md",
            "artifacts/v1.0.1/tracked-file-inventory.json",
        ],
    )
    monkeypatch.setattr(verifier, "_digest", lambda path: f"sha256:{path.name}")

    first = verifier._inventory(tmp_path)
    second = verifier._inventory(tmp_path)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    self_entry = next(
        item
        for item in first["files"]
        if item["path"] == "artifacts/v1.0.1/tracked-file-inventory.json"
    )
    assert self_entry["bytes"] is None
    assert self_entry["sha256"] == "SELF_REFERENCE_OMITTED"
