from __future__ import annotations

import json
from pathlib import Path

from radar_bench.cli import build_parser, main
from radar_bench.config import package_resource_root
from radar_bench.v1_2 import (
    ALL_CASE_IDS,
    ExperimentLedger,
    ExternalCandidateProtocol,
    V12_SUITE_ID,
    candidate_bundle_audit,
    generate_episode_ids,
    information_sufficiency_audit,
    source_package_mirror_audit,
    validate_experiment_request,
)


ROOT = Path(__file__).resolve().parents[1]


def test_v12_candidate_and_evaluator_bundles_are_separate() -> None:
    audit = information_sufficiency_audit(ROOT)
    assert audit["status"] == "PASS"
    candidate = json.loads(
        (ROOT / "candidate/decisive-v1.2/candidate-bundle.json").read_text(encoding="utf-8")
    )
    assert candidate_bundle_audit(ROOT)["valid"] is True
    assert "gold_provenance" not in candidate
    assert "action_owner_repository" not in json.dumps(candidate)
    assert source_package_mirror_audit(ROOT)["status"] == "PASS"


def test_episode_ids_are_fresh_and_case_mapping_is_not_derivable() -> None:
    first = generate_episode_ids()
    second = generate_episode_ids()
    assert set(first) == set(ALL_CASE_IDS)
    assert set(second) == set(ALL_CASE_IDS)
    assert set(first.values()).isdisjoint(second.values())
    assert all(case_id not in episode_id for case_id, episode_id in first.items())


def test_experiment_parameters_are_checked_before_execution() -> None:
    assert validate_experiment_request({"capability": "missing"}) == [
        "UNSUPPORTED_CAPABILITY"
    ]
    assert "MISSING_PARAMETER:version" in validate_experiment_request(
        {"capability": "change_dependency_version", "parameters": {"target_component": "scipy"}}
    )

    calls: list[dict[str, object]] = []
    ledger = ExperimentLedger()
    response = ledger.run(
        {"capability": "rerun", "parameters": {}},
        lambda request: calls.append(dict(request)) or {"status": "COMPLETED", "result": {"useful": True}},
    )
    assert response["fresh"] is True
    assert response["cache_hit"] is False
    assert ledger.summary()["fresh_useful_experiment_rate"]["value"] == 1.0
    assert len(calls) == 1


def test_external_protocol_fails_closed_without_container_network_proof(tmp_path: Path) -> None:
    protocol = ExternalCandidateProtocol(["python", "candidate.py"], working_directory=tmp_path)
    result = protocol.run([])
    assert result["status"] == "BLOCKED"
    assert result["error"] == "CANDIDATE_ISOLATION_NOT_PROVEN"


def test_package_resources_are_manifest_materialized(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RADAR_BENCH_CACHE", str(tmp_path / "cache"))
    root = package_resource_root()
    manifest = root / "resource-manifest.json"
    assert manifest.is_file()
    assert not (root / ".materialized").exists()
    document = json.loads(manifest.read_text(encoding="utf-8"))
    assert document["schema_version"] == "1"
    assert document["files"]


def test_cli_exposes_v12_candidate_protocol() -> None:
    parsed = build_parser().parse_args(
        ["evaluate", "--suite", V12_SUITE_ID, "--candidate-command", "docker", "run"]
    )
    assert parsed.candidate_command == ["docker", "run"]
    assert main(["validate", "--suite", V12_SUITE_ID]) in {0, 2}
