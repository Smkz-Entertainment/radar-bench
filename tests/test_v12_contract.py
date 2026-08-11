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
    build_candidate_packets,
    canonical_digest,
    generate_episode_ids,
    information_sufficiency_audit,
    source_package_mirror_audit,
    validate_v12_result_document,
    validate_experiment_request,
)


ROOT = Path(__file__).resolve().parents[1]


def test_v12_candidate_and_evaluator_bundles_are_separate() -> None:
    audit = information_sufficiency_audit(ROOT)
    assert audit["status"] == "BLOCKED_INFORMATION_SUFFICIENCY"
    assert audit["evaluator_loaded"] is False
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


def test_evaluator_binding_survives_one_hundred_randomized_orders() -> None:
    candidate = json.loads((ROOT / "candidate/decisive-v1.2/candidate-bundle.json").read_text(encoding="utf-8"))
    evaluator = json.loads((ROOT / "evaluator/decisive-v1.2/evaluator-bundle.json").read_text(encoding="utf-8"))
    expected = {item["record_id"]: canonical_digest(item["evidence"]) for item in candidate["cases"]}
    for seed in range(100):
        class Randomizer:
            def shuffle(self, values):
                import random
                random.Random(seed).shuffle(values)

        episodes = generate_episode_ids()
        packets = build_candidate_packets(candidate, evaluator["record_case_mapping"], episodes, randomizer=Randomizer())
        by_case = {evaluator["record_case_mapping"][record_id]: expected[record_id] for record_id in expected}
        assert {packet.episode_id: canonical_digest(packet.evidence) for packet in packets} == {
            episodes[case_id]: digest for case_id, digest in by_case.items()
        }


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
        {"capability": "rerun", "parameters": {"command": ["python", "reproducer.py"]}},
        lambda request: calls.append(dict(request)) or {"status": "COMPLETED", "result": {"useful": True}},
    )
    assert response["fresh"] is True
    assert response["cache_hit"] is False
    assert ledger.summary()["fresh_useful_experiment_rate"]["value"] == 1.0
    assert len(calls) == 1


def test_experiment_budget_rejects_the_fourth_request() -> None:
    ledger = ExperimentLedger()
    request = {"capability": "inspect_environment", "parameters": {}, "request_id": "r"}
    for index in range(3):
        request["request_id"] = f"r-{index}"
        assert ledger.run(request, lambda _request: {"status": "COMPLETED", "result": {"useful": True}})["executor_calls"] == 1
    request["request_id"] = "r-3"
    rejected = ledger.run(request, lambda _request: {"status": "COMPLETED"})
    assert rejected["error_codes"] == ["EXPERIMENT_BUDGET_EXHAUSTED"]
    assert ledger.summary()["requested"] == 4


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
        ["evaluate", "--suite", V12_SUITE_ID, "--candidate-image", "registry/python@sha256:" + "a" * 64, "--candidate-argv", "python", "candidate.py"]
    )
    assert parsed.candidate_image.endswith("a" * 64)
    assert parsed.candidate_argv == ["python", "candidate.py"]
    assert main(["validate", "--suite", V12_SUITE_ID]) in {0, 2}


def test_v12_blocked_result_routes_through_v12_contract() -> None:
    result = {
        "schema_version": "1.2-jsonl",
        "suite_id": V12_SUITE_ID,
        "status": "BLOCKED",
        "candidate_gold_visible": False,
        "candidate_repository_visible": False,
        "network_used": False,
        "blockers": ["BLOCKED_INFORMATION_SUFFICIENCY"],
    }
    assert validate_v12_result_document(result) == []
