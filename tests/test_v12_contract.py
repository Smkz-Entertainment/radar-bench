from __future__ import annotations

import json
from pathlib import Path

import pytest

import radar_bench.v1_2 as v12
import radar_bench.v12_executor as v12_executor_module
from radar_bench.cli import build_parser, main
from radar_bench.config import package_resource_root
from radar_bench.execution.process import BoundedCapture
from radar_bench.v1_2 import (
    ALL_CASE_IDS,
    ExperimentLedger,
    ExternalCandidateProtocol,
    METRICS,
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
from radar_bench.v12_executor import V12ExperimentExecutor, normalize_python_command


ROOT = Path(__file__).resolve().parents[1]


def test_v12_candidate_and_evaluator_bundles_are_separate() -> None:
    audit = information_sufficiency_audit(ROOT)
    expected_status = "PASS" if (ROOT / "artifacts/v1.1.0/solvability-reference.json").is_file() else "BLOCKED_INFORMATION_SUFFICIENCY"
    assert audit["status"] == expected_status
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
        {"capability": "rerun", "parameters": {}, "request_id": "rerun-1"},
        lambda request: calls.append(dict(request)) or {
            "status": "COMPLETED",
            "evaluator_receipt": {"fresh": True, "available": True, "useful": True},
        },
    )
    assert response["fresh"] is True
    assert response["cache_hit"] is False
    assert ledger.summary()["fresh_useful_experiment_rate"]["value"] == 1.0
    assert len(calls) == 1
    forged = ExperimentLedger().run(
        {"capability": "rerun", "parameters": {}, "request_id": "forged"},
        lambda _request: {"status": "COMPLETED", "result": {"fresh": True, "useful": True}},
    )
    assert forged["fresh"] is False
    assert forged["useful"] is False
    assert "UNEXPECTED_PARAMETER:command" in validate_experiment_request(
        {"capability": "rerun", "parameters": {"command": ["python", "x.py"]}}
    )


def test_historical_commands_are_normalized_without_duplicate_interpreter() -> None:
    assert normalize_python_command(["python", "/reproducer/test.py"], interpreter="python") == ["python", "/reproducer/test.py"]
    assert normalize_python_command(["python", "-X", "faulthandler", "/reproducer/test.py"], interpreter="python") == ["python", "-X", "faulthandler", "/reproducer/test.py"]
    with pytest.raises(ValueError):
        normalize_python_command(["bash", "/reproducer/test.py"])
    executor = V12ExperimentExecutor(ROOT, episode_to_case={"episode": "RADAR-V07-A01"})
    runtime = executor.recipes["RADAR-V07-A01"]
    command = executor._command_for(runtime, "control", {"capability": "rerun", "parameters": {}})
    assert command is not None
    assert command[0] == "python"
    assert command[1] != "python"


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
        "release_version": "1.1.0",
        "status": "BLOCKED",
        "candidate_gold_visible": False,
        "candidate_repository_visible": False,
        "network_used": False,
        "blockers": ["BLOCKED_INFORMATION_SUFFICIENCY"],
    }
    assert validate_v12_result_document(result) == []


def test_v12_completed_result_round_trip_requires_provenance_and_cleanup() -> None:
    prediction = {
        "causal_component": None,
        "candidate_induced": False,
        "semantic_intent": "not-applicable",
        "action_owner": None,
        "disposition": "ABSTAINED",
        "evidence_ids": [],
    }
    digest = "sha256:" + "a" * 64
    metric = {"value": None, "numerator": 0, "denominator": 0, "status": "not_evaluable"}
    result = {
        "schema_version": "1.2-jsonl",
        "suite_id": V12_SUITE_ID,
        "release_version": "1.1.0",
        "status": "COMPLETED",
        "candidate_gold_visible": False,
        "candidate_repository_visible": False,
        "network_used": False,
        "episode_ids": "evaluator-only-random-per-run",
        "blockers": [],
        "protocol": {"version": "1.2-jsonl", "docker_isolated": True, "network_denied": True},
        "runs": {case_id: {"prediction": prediction, "ledger": {}} for case_id in ALL_CASE_IDS},
        "episode_count": 25,
        "mapping_digest": digest,
        "metrics": {name: metric for name in METRICS},
        "candidate_bundle_digest": digest,
        "evaluator_bundle_digest": digest,
        "runtime_digest": digest,
        "artifact_catalog_digest": digest,
        "baseline_digests": {"baseline": digest},
        "protocol_version": "1.2-jsonl",
        "executor_capability_version": "radar-v12-executor-receipt-1",
        "platform_contract": {"os": "linux", "architecture": "x86_64", "runtime": "docker", "network": "none"},
        "isolation_verification": {"candidate_gold_hidden": True, "candidate_repository_hidden": True, "network_denied": True, "cleanup_verified": True},
        "experiment_receipts": {case_id: {} for case_id in ALL_CASE_IDS},
        "predictions": {case_id: prediction for case_id in ALL_CASE_IDS},
        "source_provenance": {"suite": digest, "candidate_bundle": digest, "evaluator_bundle": digest, "runtime": digest, "artifact_catalog": digest, "baseline": digest},
        "cleanup_status": {"candidate_container": "VERIFIED", "experiment_containers": "VERIFIED", "preparation_volumes": "VERIFIED", "errors": []},
        "decision": "COMPLETED",
        "scientific_classification": "SCIENTIFICALLY_EVALUABLE",
    }
    assert validate_v12_result_document(json.loads(json.dumps(result))) == []
    result["blockers"] = ["forged-blocker"]
    assert validate_v12_result_document(result)


def test_v12_pure_validation_lanes_cover_invalid_and_valid_packets() -> None:
    candidate = json.loads((ROOT / "candidate/decisive-v1.2/candidate-bundle.json").read_text(encoding="utf-8"))
    evidence = dict(candidate["cases"][0]["evidence"])
    assert v12.validate_candidate_evidence(evidence) == []
    assert v12.validate_candidate_evidence({})
    document = dict(candidate)
    assert v12.validate_candidate_document(document) == []
    document["cases"] = []
    assert v12.validate_candidate_document(document)
    assert v12.metadata_shape_classifier_audit(candidate)["status"] == "PASS"
    assert v12.validate_experiment_request({"capability": "rerun", "parameters": {}}) == []
    assert v12.validate_experiment_request({"capability": "rerun", "parameters": {"command": []}})
    assert v12.validate_protocol_message({"schema_version": "bad"})
    assert v12.validate_prediction({
        "causal_component": None,
        "candidate_induced": False,
        "semantic_intent": "not-applicable",
        "action_owner": None,
        "disposition": "ABSTAINED",
        "evidence_ids": [],
    }) == []
    assert v12.validate_prediction({})


def test_v12_mapping_packets_sandbox_and_manifest_helpers(tmp_path: Path) -> None:
    candidate = json.loads((ROOT / "candidate/decisive-v1.2/candidate-bundle.json").read_text(encoding="utf-8"))
    episodes = v12.generate_episode_ids()
    evaluator = json.loads((ROOT / "evaluator/decisive-v1.2/evaluator-bundle.json").read_text(encoding="utf-8"))
    packets = v12.build_candidate_packets(candidate, evaluator["record_case_mapping"], episodes)
    assert len(packets) == 25
    assert v12.validate_record_case_mapping(evaluator["record_case_mapping"]) == []
    assert v12.validate_record_case_mapping({})
    image = "registry.example/python@sha256:" + "a" * 64
    argv = v12.build_candidate_docker_argv(image, ["python", "-c", "pass"], "radar-candidate-test")
    assert v12.validate_sandbox_argv(argv) == []
    assert v12.verify_actual_container_config({})
    manifest = v12.build_file_manifest(ROOT, [ROOT / "README.md"])
    assert v12.validate_file_manifest(ROOT, manifest)["valid"] is True
    assert v12.validate_file_manifest(ROOT, {"files": []})["valid"] is False
    assert v12.compare_exact_reference({"suite_id": "x"}, None)["status"] == "NO_REFERENCE"
    with v12.secure_temp_workspace("radar-test-") as workspace:
        assert Path(workspace).name.startswith("radar-test-")
    assert v12.separation_audit(ROOT)["valid"] is True
    assert v12.source_package_mirror_audit(ROOT)["status"] == "PASS"
    assert not tmp_path.joinpath("unused").exists()


def test_v12_executor_command_and_cleanup_failure_lanes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_root = tmp_path / "external" / "decisive-v1.2"
    (artifact_root / "pandas-55137-wheelhouse").mkdir(parents=True)
    monkeypatch.setattr(
        v12_executor_module,
        "verify_artifacts",
        lambda *_args, **_kwargs: {"status": "READY", "errors": [], "bundles": []},
    )
    executor = v12_executor_module.V12ExperimentExecutor(
        ROOT,
        episode_to_case={"episode": "RADAR-V07-A01"},
        artifact_root=artifact_root,
    )
    runtime = executor.recipes["RADAR-V07-A01"]
    request = {"capability": "rerun", "parameters": {}}
    assert executor._command_for(runtime, "control", {"capability": "inspect_environment", "parameters": {}})
    assert executor._command_for(runtime, "control", {"capability": "run_minimal_test", "parameters": {}}) is None
    assert executor._command_for(runtime, "control", {"capability": "run_minimal_test", "parameters": {"test_id": "sealed-reproducer"}})
    assert executor._requires_site_volume(runtime, "control") is True
    installing = executor._installing_command(runtime, "control", ["python", "/reproducer/test.py"], request)
    assert installing is not None and "/opt/radar/site" in installing[-1]
    assert executor._docker_argv(runtime, "control", installing, tmp_path, site_volume="invalid") is None
    (tmp_path / "input").mkdir()
    argv = executor._docker_argv(runtime, "control", installing, tmp_path / "input", site_volume="radar-v12-site-" + "a" * 16)
    assert argv is not None and "volume-nocopy" in " ".join(argv)
    assert executor._audit_preparation_output(tmp_path / "input", [])[0] is True
    assert executor("unknown", request)["observation"]["status"] == "EPISODE_NOT_BOUND"
    monkeypatch.setattr(v12_executor_module.shutil, "which", lambda _name: None)
    assert executor("episode", request)["observation"]["status"] == "DOCKER_UNAVAILABLE"

    capture = BoundedCapture(0, 0, "sha256:" + "0" * 64, False, False, "")
    calls: list[list[str]] = []
    monkeypatch.setattr(v12_executor_module.shutil, "which", lambda _name: "docker")
    monkeypatch.setattr(v12_executor_module, "run_bounded", lambda argv, **_kwargs: calls.append(list(argv)) or capture)
    monkeypatch.setattr(executor, "_cleanup_container", lambda _name: {"cleanup_verified": True})
    monkeypatch.setattr(executor, "_cleanup_volume", lambda _name: {"cleanup_verified": True})
    result = executor._run_side(runtime, "control", ["python", "/reproducer/test.py"], tmp_path / "input", request)
    assert result is capture
    assert any("volume" in call for call in calls)


def test_v12_executor_call_observes_safety_pair_and_request_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = v12_executor_module.V12ExperimentExecutor(ROOT, episode_to_case={"episode": "RADAR-V07-T01"})
    capture = BoundedCapture(0, 3, "sha256:" + "1" * 64, False, False, "ok\n")
    monkeypatch.setattr(v12_executor_module.shutil, "which", lambda _name: "docker")
    monkeypatch.setattr(executor, "_run_side", lambda *_args, **_kwargs: capture)
    result = executor("episode", {"capability": "rerun", "parameters": {}})
    assert result["status"] == "COMPLETED"
    assert result["evaluator_receipt"]["fresh"] is True
    assert result["observation"]["useful"] is True
    invalid = executor("episode", {"capability": "run_minimal_test", "parameters": {}})
    assert invalid["status"] == "INVALID_REQUEST"
    unsupported = executor("episode", {"capability": "change_dependency_version", "parameters": {}})
    assert unsupported["status"] == "UNSUPPORTED_EXPERIMENT"
