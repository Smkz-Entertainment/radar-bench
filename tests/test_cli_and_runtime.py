from __future__ import annotations

from pathlib import Path

import pytest

from radar_bench.cli import build_parser, main
from radar_bench.execution.canonical import validate_candidate_view
from radar_bench.historical_runtime import _copy_declared_outputs
from radar_bench.release import inspect_case


ROOT = Path(__file__).resolve().parents[1]


def test_public_cli_help_exposes_only_v11_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["doctor"]).command == "doctor"
    with pytest.raises(SystemExit):
        parser.parse_args(["validate", "--suite", "decisive-v1"])
    assert main(["list-suites"]) == 0
    assert main(["inspect-case", "not-a-real-case"]) == 2


def test_inspect_case_does_not_load_gold() -> None:
    result = inspect_case(ROOT, "RADAR-V07-A02")
    assert result["runtime_visible"] is False
    assert result["gold_loaded"] is False


def test_candidate_view_rejects_gold_fields() -> None:
    errors = validate_candidate_view(
        {
            "schema_version": "1.1-canonical",
            "episode_id": "opaque",
            "capabilities": ["rerun"],
            "allowed_components": [],
            "visible_evidence": [],
            "gold": "forbidden",
        }
    )
    assert any("evaluator-only" in error for error in errors)


def test_preparation_output_inventory_is_exact(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    destination = tmp_path / "destination"
    staging.mkdir()
    destination.mkdir()
    (staging / "fixture.dat").write_bytes(b"fixture")
    ok, error, report = _copy_declared_outputs(
        staging, destination, ["fixture.dat"]
    )
    assert ok is True
    assert error is None
    assert report["observed"] == ["fixture.dat"]
    assert (destination / "fixture.dat").read_bytes() == b"fixture"
    (staging / "extra.dat").write_bytes(b"extra")
    ok, error, _ = _copy_declared_outputs(staging, destination, ["fixture.dat"])
    assert ok is False
    assert error == "PREPARATION_OUTPUT_INVENTORY_MISMATCH"
