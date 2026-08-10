from __future__ import annotations

import os
from pathlib import Path

import pytest

import radar_bench.execution.v07 as v07
import radar_bench.historical_runtime as historical_runtime
from radar_bench.cli import build_parser, main
from radar_bench.execution.canonical import validate_candidate_view
from radar_bench.execution.process import BoundedCapture
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


def test_preparation_output_rejects_hardlinks(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    destination = tmp_path / "destination"
    staging.mkdir()
    destination.mkdir()
    source = staging / "source.dat"
    linked = staging / "linked.dat"
    source.write_bytes(b"fixture")
    os.link(source, linked)
    ok, error, _ = _copy_declared_outputs(
        staging, destination, ["source.dat", "linked.dat"]
    )
    assert ok is False
    assert error == "PREPARATION_OUTPUT_HARDLINK"


def test_preparation_output_rejects_directories_and_file_flood(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    destination = tmp_path / "destination"
    staging.mkdir()
    destination.mkdir()
    (staging / "nested").mkdir()
    ok, error, _ = _copy_declared_outputs(staging, destination, [])
    assert ok is False
    assert error == "PREPARATION_OUTPUT_INVALID"

    flood = tmp_path / "flood"
    flood.mkdir()
    for index in range(17):
        (flood / f"{index}.dat").write_bytes(b"x")
    ok, error, _ = _copy_declared_outputs(
        flood, destination, [f"{index}.dat" for index in range(17)]
    )
    assert ok is False
    assert error == "PREPARATION_OUTPUT_TOO_MANY_FILES"


def test_cleanup_verification_fails_closed_when_inspection_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_inspection(argv: list[str], **_kwargs: object) -> dict[str, object]:
        if "inspect" in argv or "ps" in argv or "volume" in argv or ("image" in argv and "ls" in argv):
            return {"returncode": None, "error_type": "OSError", "_output": b""}
        return {"returncode": 0, "_output": b""}

    monkeypatch.setattr(historical_runtime, "_run_docker", failed_inspection)
    assert historical_runtime._remove_container("docker", "container")["cleanup_verified"] is False
    assert historical_runtime._remove_volume("docker", "volume")["cleanup_verified"] is False
    assert historical_runtime._remove_image("docker", "image")["cleanup_verified"] is False

    monkeypatch.setattr(
        v07,
        "run_bounded",
        lambda *_args, **_kwargs: BoundedCapture(
            returncode=None,
            output_bytes=0,
            output_digest="sha256:" + "0" * 64,
            output_limit_exceeded=False,
            timed_out=False,
            excerpt="",
            cleanup_error="inspection failed",
        ),
    )
    assert v07._cleanup_container("docker", "container")["cleanup_verified"] is False


def test_cleanup_verification_rejects_nonzero_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    def nonzero_listing(argv: list[str], **_kwargs: object) -> dict[str, object]:
        if "ps" in argv or "volume" in argv or ("image" in argv and "ls" in argv):
            return {"returncode": 1, "_output": b""}
        return {"returncode": 0, "_output": b""}

    monkeypatch.setattr(historical_runtime, "_run_docker", nonzero_listing)
    assert historical_runtime._remove_container("docker", "container")["cleanup_verified"] is False
    assert historical_runtime._remove_volume("docker", "volume")["cleanup_verified"] is False
    assert historical_runtime._remove_image("docker", "image")["cleanup_verified"] is False

    monkeypatch.setattr(
        v07,
        "run_bounded",
        lambda *_args, **_kwargs: BoundedCapture(
            returncode=1,
            output_bytes=0,
            output_digest="sha256:" + "0" * 64,
            output_limit_exceeded=False,
            timed_out=False,
            excerpt="",
        ),
    )
    assert v07._cleanup_container("docker", "container")["cleanup_verified"] is False


def test_cleanup_listing_templates_are_valid_docker_templates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def successful_docker(argv: list[str], **_kwargs: object) -> dict[str, object]:
        calls.append(argv)
        return {"returncode": 0, "_output": b""}

    monkeypatch.setattr(historical_runtime, "_run_docker", successful_docker)
    monkeypatch.setattr(
        v07,
        "run_bounded",
        lambda argv, **_kwargs: (
            calls.append(argv)
            or BoundedCapture(
                returncode=0,
                output_bytes=0,
                output_digest="sha256:" + "0" * 64,
                output_limit_exceeded=False,
                timed_out=False,
                excerpt="",
            )
        ),
    )

    historical_runtime._remove_container("docker", "container")
    historical_runtime._remove_volume("docker", "volume")
    historical_runtime._remove_image("docker", "image")
    v07._cleanup_container("docker", "container")

    assert ["--format", "{{.Names}}"] in [
        argv[-2:] for argv in calls if "ps" in argv
    ]
    assert ["--format", "{{.Name}}"] in [
        argv[-2:] for argv in calls if "volume" in argv and "ls" in argv
    ]
    assert ["--format", "{{.Repository}}:{{.Tag}}"] in [
        argv[-2:] for argv in calls if "image" in argv and "ls" in argv
    ]
