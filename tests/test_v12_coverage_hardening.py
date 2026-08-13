from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import subprocess
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

import radar_bench.v1_2 as v12
import radar_bench.v12_executor as executor_module
import radar_bench.artifacts as artifacts
import radar_bench.execution.canonical as canonical
import radar_bench.execution.v07 as v07
import radar_bench.historical_runtime as historical
import radar_bench.investigation.v01 as investigation
import radar_bench.release as release
import radar_bench.config as config
import radar_bench.cli as cli
import radar_bench.providers.subprocess_provider as provider_module
from radar_bench.providers.base import inference_packet
from radar_bench.execution.process import BoundedCapture
import radar_bench.execution.process as process_module


ROOT = Path(__file__).resolve().parents[1]
ZERO_DIGEST = "sha256:" + "0" * 64


def _candidate() -> dict[str, Any]:
    return json.loads(
        (ROOT / "candidate/decisive-v1.2/candidate-bundle.json").read_text(
            encoding="utf-8"
        )
    )


def _evaluator() -> dict[str, Any]:
    return json.loads(
        (ROOT / "evaluator/decisive-v1.2/evaluator-bundle.json").read_text(
            encoding="utf-8"
        )
    )


def _prediction(
    *,
    disposition: str = "ABSTAINED",
    candidate_induced: bool = False,
    component: str | None = None,
    semantic_intent: str = "not-applicable",
    owner: str | None = None,
) -> dict[str, Any]:
    return {
        "causal_component": component,
        "candidate_induced": candidate_induced,
        "semantic_intent": semantic_intent,
        "action_owner": owner,
        "disposition": disposition,
        "evidence_ids": [],
    }


def _completed_result() -> dict[str, Any]:
    digest = ZERO_DIGEST
    predictions = {case_id: _prediction() for case_id in v12.ALL_CASE_IDS}
    return {
        "schema_version": v12.V12_PROTOCOL_VERSION,
        "suite_id": v12.V12_SUITE_ID,
        "release_version": v12.V12_RELEASE_VERSION,
        "status": "COMPLETED",
        "candidate_gold_visible": False,
        "candidate_repository_visible": False,
        "network_used": False,
        "episode_ids": "evaluator-only-random-per-run",
        "blockers": [],
        "protocol": {
            "version": v12.V12_PROTOCOL_VERSION,
            "docker_isolated": True,
            "network_denied": True,
        },
        "runs": {
            case_id: {"prediction": prediction, "ledger": {}}
            for case_id, prediction in predictions.items()
        },
        "episode_count": len(v12.ALL_CASE_IDS),
        "mapping_digest": digest,
        "metrics": {name: v12._metric(0, 0) for name in v12.METRICS},
        "candidate_bundle_digest": digest,
        "evaluator_bundle_digest": digest,
        "runtime_digest": digest,
        "artifact_catalog_digest": digest,
        "baseline_digests": {"baseline": digest},
        "protocol_version": v12.V12_PROTOCOL_VERSION,
        "executor_capability_version": "radar-v12-executor-receipt-1",
        "platform_contract": {
            "os": "linux",
            "architecture": "x86_64",
            "runtime": "docker",
            "network": "none",
        },
        "isolation_verification": {
            "candidate_gold_hidden": True,
            "candidate_repository_hidden": True,
            "network_denied": True,
            "cleanup_verified": True,
        },
        "experiment_receipts": {case_id: {} for case_id in v12.ALL_CASE_IDS},
        "predictions": predictions,
        "source_provenance": {
            "suite": digest,
            "candidate_bundle": digest,
            "evaluator_bundle": digest,
            "runtime": digest,
            "artifact_catalog": digest,
            "baseline": digest,
        },
        "cleanup_status": {
            "candidate_container": "VERIFIED",
            "experiment_containers": "VERIFIED",
            "preparation_volumes": "VERIFIED",
            "errors": [],
        },
        "decision": "COMPLETED",
        "scientific_classification": "SCIENTIFICALLY_EVALUABLE",
    }


def test_v12_validation_matrix_and_label_provenance(tmp_path: Path) -> None:
    candidate = _candidate()
    evidence = dict(candidate["cases"][0]["evidence"])
    assert v12.validate_candidate_evidence(evidence) == []
    assert v12.validate_candidate_evidence({"context": [], "source_location_evidence": [1]})

    malformed = copy.deepcopy(candidate)
    malformed["schema_version"] = "bad"
    malformed["resource_policy"] = []
    malformed["protocol"] = []
    malformed["capabilities"] = "all"
    malformed["cases"] = [{"record_id": "record-001", "evidence": {}}]
    errors = v12.validate_candidate_document(malformed)
    assert errors
    assert v12.metadata_shape_classifier_audit({})["status"] == "BLOCKED"
    token_document = copy.deepcopy(candidate)
    token_document["cases"][0]["evidence"]["context"]["token"] = "safety-twin"
    assert v12.metadata_shape_classifier_audit(token_document)["status"] == "BLOCKED"

    requests = [
        {"capability": capability, "parameters": {}}
        for capability in v12.CAPABILITIES
        if capability not in {"run_minimal_test", "change_dependency_version"}
    ]
    requests.extend(
        [
            {
                "capability": "run_minimal_test",
                "parameters": {"test_id": "sealed-reproducer"},
            },
            {
                "capability": "change_dependency_version",
                "parameters": {"target_component": "scipy", "version": "1"},
            },
        ]
    )
    assert all(not v12.validate_experiment_request(request) for request in requests)
    assert v12.validate_experiment_request({"capability": "rerun", "parameters": []})
    assert v12.validate_experiment_request(
        {"capability": "rerun", "parameters": {"cache": True}}
    )
    assert v12.validate_experiment_request(
        {
            "capability": "change_dependency_version",
            "parameters": {"target_component": 1, "version": 2},
        }
    )

    experiment = {
        "schema_version": v12.V12_PROTOCOL_VERSION,
        "message": "experiment_request",
        "episode_id": "episode",
        "request_id": "request",
        "capability": "rerun",
        "parameters": {},
    }
    assert v12.validate_protocol_message(experiment) == []
    assert v12.validate_protocol_message(experiment, expected="final_prediction")
    final = {
        "schema_version": v12.V12_PROTOCOL_VERSION,
        "message": "final_prediction",
        "episode_id": "episode",
        "prediction": _prediction(),
    }
    assert v12.validate_protocol_message(final) == []
    assert v12.validate_protocol_message({"message": "other"}) == [
        "UNKNOWN_CANDIDATE_MESSAGE"
    ]
    assert v12.validate_protocol_message({"message": "final_prediction", "prediction": []})
    assert v12.validate_prediction(
        {
            "causal_component": 1,
            "candidate_induced": "no",
            "semantic_intent": "bad",
            "action_owner": 1,
            "disposition": "bad",
            "evidence_ids": [1],
        }
    )

    evaluator = _evaluator()
    valid_label = evaluator["labels"]["cases"]["RADAR-V07-A01"]
    assert v12.validate_label_case("A01", valid_label) == []
    bad_label = copy.deepcopy(valid_label)
    bad_label["candidate_induced"] = "yes"
    bad_label["causal_component_scored"] = True
    bad_label["causal_component"] = None
    bad_label["tcut"] = "bad"
    bad_label["gold_evidence_ids"] = []
    assert v12.validate_label_case("A01", bad_label)
    assert v12.validate_label_document({"schema_version": "bad"})
    label_document = {"schema_version": "1.2", "cases": {"unknown": valid_label}}
    assert v12.validate_label_document(label_document)
    assert v12.validate_gold_provenance({}, ROOT)
    provenance = evaluator["gold_provenance"]
    assert v12.validate_gold_provenance(provenance, ROOT) == []

    bad_provenance = copy.deepcopy(provenance)
    records = bad_provenance["records"] if isinstance(bad_provenance, dict) else bad_provenance
    assert isinstance(records, list)
    records[0]["immutable_digest"] = "bad"
    records[0]["source_url"] = "http://bad"
    records[0]["source_references"] = []
    records[0]["source_reference_timestamps"] = ["bad"]
    records[0]["source_reference_digests"] = ["bad"]
    records.append("not-an-object")
    assert v12.validate_gold_provenance(bad_provenance, tmp_path)


def test_v12_scoring_exercises_historical_safety_and_ledgers() -> None:
    labels = _evaluator()["labels"]["cases"]
    runs: dict[str, dict[str, Any]] = {}
    for case_id, label in labels.items():
        if case_id == "RADAR-V07-A03":
            prediction = _prediction(
                disposition="AMBIGUOUS", semantic_intent="ambiguous"
            )
        elif case_id.startswith("RADAR-V07-A"):
            prediction = _prediction(
                disposition="ATTRIBUTED",
                candidate_induced=bool(label["candidate_induced"]),
                component=label["causal_component"],
                semantic_intent=label["semantic_intent"],
                owner=label["action_owner_repository"],
            )
        else:
            prediction = _prediction(
                disposition="ABSTAINED",
                candidate_induced=bool(label["candidate_induced"]),
            )
        runs[case_id] = {
            "prediction": prediction,
            "ledger": {
                "attempts": [
                    {"requested": True, "fresh": True, "useful": True},
                    {"requested": True, "fresh": False, "useful": False},
                ]
            },
        }
    scored = v12.score_v12(labels, runs)
    assert scored["metrics"]["historical_attribution_resolution"]["denominator"] == 4
    assert scored["metrics"]["semantic_ambiguity_handling"]["value"] == 1.0
    assert scored["metrics"]["safety_abstention_recall"]["value"] == 1.0
    sparse = v12.score_v12(labels, {"RADAR-V07-A01": {"prediction": _prediction()}})
    assert sparse["metrics"]["fresh_useful_experiment_rate"]["denominator"] == 0


def test_v12_result_document_rejects_each_completed_contract_lane() -> None:
    valid = _completed_result()
    assert v12.validate_v12_result_document(valid) == []
    mutations = [
        {"unexpected": True},
        {"blockers": ["forged"]},
        {"episode_count": 1},
        {"runs": {"RADAR-V07-A01": {}}},
        {"protocol": {}},
        {"metrics": {}},
        {"predictions": {}},
        {"experiment_receipts": {}},
        {"candidate_bundle_digest": "bad"},
        {"baseline_digests": {}},
        {"platform_contract": {"network": "host"}},
        {"isolation_verification": {}},
        {"source_provenance": {}},
        {"cleanup_status": {}},
    ]
    for mutation in mutations:
        candidate = copy.deepcopy(valid)
        candidate.update(mutation)
        assert v12.validate_v12_result_document(candidate)
    blocked = {
        "schema_version": v12.V12_PROTOCOL_VERSION,
        "suite_id": v12.V12_SUITE_ID,
        "release_version": v12.V12_RELEASE_VERSION,
        "status": "BLOCKED",
        "candidate_gold_visible": False,
        "candidate_repository_visible": False,
        "network_used": False,
        "blockers": ["reason"],
    }
    assert v12.validate_v12_result_document(blocked) == []


def test_v12_mapping_sandbox_and_manifest_error_lanes(tmp_path: Path) -> None:
    candidate = _candidate()
    evaluator = _evaluator()
    mapping = evaluator["record_case_mapping"]
    episodes = v12.generate_episode_ids()
    packets = v12.build_candidate_packets(candidate, mapping, episodes)
    assert packets[0].as_json()["message"] == "episode_start"
    with pytest.raises(ValueError):
        v12.build_candidate_packets(candidate, {}, episodes)
    broken_candidate = copy.deepcopy(candidate)
    broken_candidate["cases"][0]["record_id"] = "record-999"
    with pytest.raises(ValueError):
        v12.build_candidate_packets(broken_candidate, mapping, episodes)
    with pytest.raises(ValueError):
        v12.build_candidate_docker_argv("python", ["python"], "bad")
    with pytest.raises(ValueError):
        v12.build_candidate_docker_argv(
            "registry/python@sha256:" + "a" * 64,
            ["python"],
            "radar-candidate-test",
            (Path("relative"), "/resources"),
        )
    argv = v12.build_candidate_docker_argv(
        "registry/python@sha256:" + "a" * 64, ["python"], "radar-candidate-test"
    )
    assert v12.validate_sandbox_argv(argv) == []
    assert v12.validate_sandbox_argv(argv + ["--privileged", "--network=none"])
    assert v12.verify_actual_container_config({})
    valid_config = {
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 512 * 1024 * 1024,
            "MemorySwap": 512 * 1024 * 1024,
            "PidsLimit": 128,
            "NanoCpus": 1_000_000_000,
            "PidMode": None,
            "UTSMode": None,
            "UsernsMode": None,
            "IpcMode": "private",
            "Devices": [],
        },
        "Config": {"User": "65532:65532"},
        "Mounts": [],
    }
    assert v12.verify_actual_container_config(valid_config) == []
    invalid_config = copy.deepcopy(valid_config)
    invalid_config["Mounts"] = [{"Type": "bind", "Source": "/var/run/docker.sock"}, 1]
    invalid_config["HostConfig"]["Memory"] = 1
    assert v12.verify_actual_container_config(invalid_config)

    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    manifest = v12.build_file_manifest(tmp_path, [source])
    assert v12.validate_file_manifest(tmp_path, manifest)["valid"] is True
    assert v12.validate_file_manifest(tmp_path, {"files": []})["valid"] is False
    escaped = copy.deepcopy(manifest)
    escaped["files"][0]["path"] = "../escape"
    assert v12.validate_file_manifest(tmp_path, escaped)["valid"] is False
    with pytest.raises(ValueError):
        v12.build_file_manifest(tmp_path, [tmp_path / "missing"])
    assert v12.compare_exact_reference({"suite_id": "x"}, {})["status"] == "EXACT_MATCH"


def test_v12_protocol_constructor_cleanup_and_inspection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    legacy = v12.ExternalCandidateProtocol(["candidate"], working_directory=tmp_path)
    assert legacy.docker_isolated is False
    assert legacy._container_name() is None
    assert legacy._cleanup_container() is False
    with pytest.raises(ValueError):
        v12.ExternalCandidateProtocol("bad", None, working_directory=tmp_path)
    protocol = v12.ExternalCandidateProtocol(
        "registry/python@sha256:" + "a" * 64,
        ["python", "-c", "pass"],
        working_directory=tmp_path,
    )
    assert protocol.docker_isolated is True

    calls: list[list[str]] = []

    def completed(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        if argv[1:2] == ["inspect"]:
            return subprocess.CompletedProcess(argv, 1, b"", b"no such object")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(v12.subprocess, "run", completed)
    assert protocol._actual_container_config()
    assert protocol._cleanup_container() is True
    assert calls

    def valid_inspect(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            ["docker", "inspect"],
            0,
            json.dumps([{
                "HostConfig": {
                    "NetworkMode": "none",
                    "ReadonlyRootfs": True,
                    "Privileged": False,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges"],
                    "Memory": 512 * 1024 * 1024,
                    "MemorySwap": 512 * 1024 * 1024,
                    "PidsLimit": 128,
                    "NanoCpus": 1_000_000_000,
                    "PidMode": None,
                    "UTSMode": None,
                    "UsernsMode": None,
                    "IpcMode": "private",
                    "Devices": [],
                },
                "Config": {"User": "65532"},
                "Mounts": [],
            }]).encode(),
            b"",
        )

    monkeypatch.setattr(v12.subprocess, "run", valid_inspect)
    assert protocol._actual_container_config() == []


def test_v12_protocol_run_full_terminal_state_with_fake_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    protocol = v12.ExternalCandidateProtocol(
        "registry/python@sha256:" + "a" * 64,
        ["python", "-c", "pass"],
        working_directory=tmp_path,
    )
    packets = [
        v12.CandidatePacket(f"episode-{index}", {}, tuple(sorted(v12.CAPABILITIES)))
        for index in range(len(v12.ALL_CASE_IDS))
    ]
    output_read, output_write = os.pipe()
    error_read, error_write = os.pipe()
    payload = b"".join(
        (
            json.dumps({
                "schema_version": v12.V12_PROTOCOL_VERSION,
                "message": "final_prediction",
                "episode_id": packet.episode_id,
                "prediction": _prediction(),
            }).encode()
            + b"\n"
        )
        for packet in packets
    )
    def write_output() -> None:
        os.write(output_write, payload)
        os.close(output_write)

    threading.Thread(target=write_output, daemon=True).start()
    os.close(error_write)

    class FakeStream:
        def __init__(self, descriptor: int) -> None:
            self.descriptor = descriptor

        def fileno(self) -> int:
            return self.descriptor

    class FakeStdin:
        def write(self, _payload: bytes) -> int:
            return len(_payload)

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeProcess:
        stdin = FakeStdin()
        stdout = FakeStream(output_read)
        stderr = FakeStream(error_read)
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, **_kwargs: object) -> int:
            self.returncode = 0
            return 0

        def kill(self) -> None:
            self.returncode = -9

    fake = FakeProcess()
    monkeypatch.setattr(v12.subprocess, "Popen", lambda *_args, **_kwargs: fake)
    monkeypatch.setattr(protocol, "_actual_container_config", lambda: [])
    monkeypatch.setattr(protocol, "_cleanup_container", lambda: True)
    result = protocol.run(packets)
    os.close(output_read)
    os.close(error_read)
    assert result["status"] == "COMPLETED"
    assert len(result["predictions"]) == len(packets)


def test_v12_audits_and_evaluate_gate_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert v12.candidate_bundle_audit(tmp_path)["valid"] is False
    bad_candidate = tmp_path / "candidate.json"
    bad_candidate.write_text("[]", encoding="utf-8")
    assert v12.candidate_bundle_audit(tmp_path)["valid"] is False
    assert v12.evaluator_bundle_audit(tmp_path)["valid"] is False
    assert v12.evaluator_bundle_audit(tmp_path, bad_candidate)["valid"] is False
    assert v12.information_sufficiency_audit(tmp_path)["status"] == "BLOCKED_INFORMATION_SUFFICIENCY"
    assert v12._runtime_audit(tmp_path)["status"] == "BLOCKED"

    blocked = v12.evaluate_v12(ROOT)
    assert blocked["status"] == "BLOCKED"
    assert "CANDIDATE_IMAGE_AND_ARGV_REQUIRED" in blocked["blockers"]
    deprecated = v12.evaluate_v12(ROOT, candidate_command=["python"])
    assert "CANDIDATE_COMMAND_DEPRECATED_USE_IMAGE_AND_ARGV" in deprecated["blockers"]

    class FakeProtocol:
        docker_isolated = True

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def run(self, packets: list[v12.CandidatePacket], **_kwargs: object) -> dict[str, Any]:
            return {
                "status": "COMPLETED",
                "network_denied": True,
                "errors": [],
                "predictions": {packet.episode_id: _prediction() for packet in packets},
                "ledgers": {packet.episode_id: {} for packet in packets},
            }

    monkeypatch.setattr(v12, "ExternalCandidateProtocol", FakeProtocol)
    result = v12.evaluate_v12(
        ROOT,
        candidate_image="registry/python@sha256:" + "a" * 64,
        candidate_argv=["python", "candidate.py"],
        evaluator_bundle_path=ROOT / "evaluator/decisive-v1.2/evaluator-bundle.json",
        artifact_root=tmp_path,
    )
    assert result["status"] == "COMPLETED"
    assert result["episode_count"] == len(v12.ALL_CASE_IDS)


def test_v12_reference_and_runtime_error_variants(tmp_path: Path) -> None:
    candidate = {"digest": ZERO_DIGEST}
    invalid = {
        "review_type": "wrong",
        "raw_predictions": [{}],
        "receipts": [{}],
        "evaluator_available_during_run": True,
        "candidate_bundle_digest": "bad",
        "historical_review": [],
        "metadata_only": {"case_type_signal": "yes", "classifier_advantage": 9},
    }
    assert v12._validate_solvability_reference(tmp_path, candidate, invalid)
    runtime = tmp_path / "corpus/v1.1.0/decisive-v1.2"
    runtime.mkdir(parents=True)
    recipe_path = runtime / "runtime-recipes.json"
    recipe_path.write_text(json.dumps({"suite_id": "bad", "recipes": [{}]}), encoding="utf-8")
    assert v12._runtime_audit(tmp_path)["status"] == "BLOCKED"
    recipe_path.write_text("[]", encoding="utf-8")
    assert v12._runtime_audit(tmp_path)["status"] == "BLOCKED"


def _wheel_bytes() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("demo-1.0.dist-info/METADATA", "Metadata-Version: 2.1\n")
    return stream.getvalue()


def test_artifact_contract_helpers_and_catalog_loaders(tmp_path: Path) -> None:
    wheel = _wheel_bytes()
    wheel_path = tmp_path / "demo-1.0-py3-none-any.whl"
    wheel_path.write_bytes(wheel)
    digest = "sha256:" + hashlib.sha256(wheel).hexdigest()
    with pytest.raises(artifacts.ArtifactContractError):
        artifacts._read_json(tmp_path / "missing.json")
    assert artifacts._sha256(wheel_path) == digest
    assert artifacts._suite_paths("decisive-v1.1")[0].name == "suite.json"
    assert artifacts._suite_paths("decisive-v1.2")[0].name == "suite.json"
    with pytest.raises(artifacts.ArtifactContractError):
        artifacts._suite_paths("unknown")
    with pytest.raises(artifacts.ArtifactContractError):
        artifacts._safe_relative(tmp_path, "../escape")
    assert artifacts._safe_name("good.whl") is True
    assert artifacts._safe_name("../bad") is False
    assert artifacts._valid_digest(digest) is True
    assert artifacts._valid_digest("bad") is False
    assert artifacts._bundle_digest({"demo.whl": (digest, len(wheel))}).startswith("sha256:")
    assert artifacts._validate_archive(tmp_path / "not-wheel.zip") == [
        "artifact is not a wheel archive"
    ]
    assert artifacts._validate_archive(wheel_path) == []
    bad_archive = tmp_path / "bad.whl"
    bad_archive.write_bytes(b"not a zip")
    assert artifacts._validate_archive(bad_archive)
    assert artifacts.default_artifact_root(ROOT, "decisive-v1.2").name == "decisive-v1.2"
    assert artifacts.catalog_digest(ROOT, "decisive-v1.2").startswith("sha256:")
    catalog, v12_bundles = artifacts._load_v12_bundles(ROOT)
    assert catalog["suite_id"] == "decisive-v1.2"
    assert len(v12_bundles) == 5
    old_catalog, old_bundles = artifacts._load_v11_bundles(ROOT, "decisive-v1.1")
    assert old_catalog["suite_id"] == "decisive-v1.1"
    assert len(old_bundles) == 5

    bundle = artifacts.ArtifactBundle(
        "demo",
        ("case",),
        (),
        "wheel",
        "x86_64",
        "3.11.0",
        len(wheel),
        artifacts._bundle_digest({"demo-1.0-py3-none-any.whl": (digest, len(wheel))}),
        "RECONSTRUCT_ONLY",
        (),
        (artifacts.ArtifactFile(wheel_path.name, digest, len(wheel)),),
    )
    artifact_root = tmp_path / "external"
    assert artifacts._verify_bundle(bundle, artifact_root)["status"] == "BLOCKED"
    bundle_dir = artifact_root / "demo"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / wheel_path.name).write_bytes(wheel)
    assert artifacts._verify_bundle(bundle, artifact_root)["status"] == "READY"
    (bundle_dir / "extra.txt").write_text("extra", encoding="utf-8")
    assert artifacts._verify_bundle(bundle, artifact_root)["status"] == "BLOCKED"


def test_artifact_url_metadata_and_download_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    filename = "demo-1.0-py3-none-any.whl"
    url = f"https://{artifacts.PYPI_FILE_HOST}/packages/a/{filename}"
    assert artifacts._approved_https_url("https://pypi.org/pypi/demo/1.0/json", "pypi.org")
    assert not artifacts._approved_https_url("http://pypi.org/x", "pypi.org")
    assert artifacts._approved_file_url(url, filename)
    assert not artifacts._approved_file_url(url, "other.whl")
    assert artifacts._pypi_project_version(filename) == ("demo", "1.0")
    with pytest.raises(artifacts.ArtifactContractError):
        artifacts._pypi_project_version("demo.tar.gz")
    with pytest.raises(artifacts.ArtifactContractError):
        artifacts._read_remote_json("https://evil.example/data")

    class Response:
        def __init__(self, payload: bytes, final_url: str = "") -> None:
            self.payload = payload
            self.final_url = final_url or url
            self.headers = {"Content-Length": str(len(payload))}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def geturl(self) -> str:
            return self.final_url

        def read(self, _size: int) -> bytes:
            payload, self.payload = self.payload, b""
            return payload

    metadata_url = "https://pypi.org/pypi/demo/1.0/json"
    monkeypatch.setattr(
        artifacts,
        "urlopen",
        lambda request, **_kwargs: Response(b'{"urls": []}', metadata_url),
    )
    assert artifacts._read_remote_json(metadata_url) == {"urls": []}
    monkeypatch.setattr(artifacts, "urlopen", lambda *_args, **_kwargs: Response(_wheel_bytes()))
    payload = _wheel_bytes()
    expected = artifacts.ArtifactFile(
        filename, "sha256:" + hashlib.sha256(payload).hexdigest(), len(payload)
    )
    destination = tmp_path / filename
    artifacts._download(url, destination, expected)
    assert destination.read_bytes() == payload
    monkeypatch.setattr(
        artifacts,
        "_read_remote_json",
        lambda _url: {"urls": [{"filename": filename, "url": url}]},
    )
    cache: dict[str, str] = {}
    assert artifacts._source_url(filename, cache) == url
    assert artifacts._source_url(filename, cache) == url


def test_artifact_fetch_and_verify_failure_lanes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert artifacts.verify_artifacts(tmp_path, "unknown")["status"] == "INVALID"
    assert artifacts.fetch_artifacts(tmp_path, "unknown")["status"] == "INVALID"
    monkeypatch.setattr(
        artifacts,
        "_load_bundles",
        lambda *_args: (_ for _ in ()).throw(artifacts.ArtifactContractError("bad")),
    )
    assert artifacts.verify_artifacts(ROOT, "decisive-v1.1")["status"] == "INVALID"
    assert artifacts.fetch_artifacts(ROOT, "decisive-v1.1")["status"] == "INVALID"


def test_canonical_executors_and_score_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    request = {
        "schema_version": "0.7",
        "request_id": "request",
        "episode_id": "episode",
        "capability": "rerun",
        "parameters": {},
    }
    historical = canonical.HistoricalObservationExecutor(
        {
            "episode": {
                "sides": {
                    "control": {"returncode": 0, "output_digest": "control"},
                    "candidate": {"returncode": 1, "output_digest": "candidate"},
                }
            }
        }
    )
    assert historical.execute({"schema_version": "bad"})["status"] == "INVALID_REQUEST"
    unsupported = dict(request, capability="inspect_dependency_graph")
    assert historical.execute(unsupported)["status"] == "UNSUPPORTED_EXPERIMENT"
    assert historical.execute(dict(request, episode_id="missing"))["status"] == "EXECUTION_ERROR"
    assert historical.execute(request)["result"]["outcome"] == "CANDIDATE_SPECIFIC"
    broken = canonical.HistoricalObservationExecutor({"episode": {"sides": {}}})
    assert broken.execute(request)["error_codes"] == ["CONTAINER_EXECUTION_FAILED"]
    bad_code = canonical.HistoricalObservationExecutor(
        {"episode": {"sides": {"control": {}, "candidate": {"returncode": 0}}}}
    )
    assert bad_code.execute(request)["status"] == "EXECUTION_ERROR"

    class FakeExecutor:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, value: dict[str, Any]) -> dict[str, Any]:
            self.calls += 1
            return {
                "status": "COMPLETED",
                "result": {
                    "outcome": "CANDIDATE_SPECIFIC" if self.calls % 2 else "NO_DISTINGUISHING_EFFECT",
                    "useful": True,
                    "candidate_induced": True,
                },
                "execution_evidence": ["evidence"],
                "observations": {},
            }

    opaque = canonical.OpaqueSafetyExecutor(
        FakeExecutor(), {"episode": "RADAR-V07-T01"}
    )
    assert opaque.execute(dict(request, episode_id="missing"))["status"] == "EXECUTION_ERROR"
    first = opaque.execute(request)
    second = opaque.execute(dict(request, request_id="second"))
    assert first["status"] == second["status"] == "COMPLETED"
    assert second["request_id"] == "second"
    case = canonical.OpaqueCase("case", "episode", "attribution", {"episode_id": "episode"})
    naive = canonical._run_naive(case, FakeExecutor())
    assert naive["candidate_visible_only"] is True
    assert canonical._metric(0, 0)["status"] == "not_evaluable"
    assert canonical._claim({"terminal": {"state": "CAUSALLY_ATTRIBUTED"}})
    assert canonical._attempts({"attempts": [1, {"useful": True}]}) == [{"useful": True}]
    assert canonical._empty_lane_metrics()["action_owner_correctness"]["denominator"] == 0

    static_predictions = json.loads(
        (ROOT / "baselines/static-v0.4/predictions.json").read_text(encoding="utf-8")
    )
    scored = canonical.score_canonical_lanes(
        ROOT,
        {
            "cases": [],
            "lanes": {
                "static-v0.4": {"predictions": static_predictions},
                "naive-deterministic": {"runs": []},
                "agentic-v0.5-frozen": {"runs": []},
            },
        },
    )
    assert set(scored["lanes"]) == {
        "static-v0.4",
        "naive-deterministic",
        "agentic-v0.5-frozen",
    }

    harness = canonical.CanonicalHarness(ROOT, None)
    suite = release.load_suite(ROOT)
    safety_manifest = canonical._read_object(
        ROOT / canonical.SAFETY_RUNTIME_RELATIVE, 16 * 1024 * 1024
    )
    cases = harness._cases(suite, safety_manifest)
    assert len(cases) == 25
    monkeypatch.setattr(canonical.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="RUNTIME_UNAVAILABLE"):
        harness._ensure_safety_image(safety_manifest)

    runtime_cases = [
        {
            "case_id": case_id,
            "sides": {
                "control": {"returncode": 0, "output_digest": "control"},
                "candidate": {"returncode": 1, "output_digest": "candidate"},
            },
        }
        for case_id in v12.HISTORICAL_IDS
    ]
    runtime = {"status": "READY", "network_used": False, "cases": runtime_cases}

    class FakeHermetic:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def execute(self, value: Mapping[str, Any]) -> dict[str, Any]:
            return {
                "status": "AVAILABLE",
                "request_id": value.get("request_id"),
                "result": {
                    "outcome": "BASELINE_NOT_STABLE",
                    "useful": False,
                    "candidate_induced": None,
                },
                "execution_evidence": [],
                "observations": {},
            }

    monkeypatch.setattr(canonical, "HermeticExecutor", FakeHermetic)
    monkeypatch.setattr(harness, "_ensure_safety_image", lambda _manifest: False)
    completed = harness.run(runtime)
    assert completed["status"] == "COMPLETED"
    assert len(completed["cases"]) == 25


def _investigation_record(
    *, corpus_kind: str = "attribution", category: str = "true_upstream_regression"
) -> dict[str, Any]:
    digest = ZERO_DIGEST
    chain = [
        {
            "evidence_id": "visible-1",
            "role": "symptom",
            "published_at": "2020-01-01T00:00:00Z",
            "available_after_cutoff": False,
            "immutable_source": True,
            "snapshot_digest": None,
            "uri": "https://example.test/visible",
        },
        {
            "evidence_id": "hidden-1",
            "role": "causal_intervention",
            "published_at": "2020-03-01T00:00:00Z",
            "available_after_cutoff": True,
            "immutable_source": True,
            "snapshot_digest": digest,
            "uri": "https://example.test/hidden",
        },
    ]
    return {
        "record_id": "RADAR-V04-COVERAGE",
        "corpus_kind": corpus_kind,
        "difficulty": "D1",
        "t0": "2020-01-01T00:00:00Z",
        "source_cutoff": "2020-02-01T00:00:00Z",
        "candidate_category": category,
        "candidate_snapshot": {"path": "candidate.json", "digest": digest},
        "gold_packet": {"path": "gold.json", "digest": digest},
        "source_chain": chain,
        "label": {
            "candidate_induced": True if corpus_kind == "attribution" else None,
            "should_abstain": corpus_kind == "safety",
            "action_owner_scored": corpus_kind == "attribution",
            "root_cause_component": "upstream_component" if corpus_kind == "attribution" else None,
            "action_owner_repository": "owner/repo" if corpus_kind == "attribution" else None,
            "first_bad": "commit" if corpus_kind == "attribution" else None,
        },
        "audit": {"record_digest": digest},
    }


def _investigation_request(kind: str = "baseline_check") -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "request_id": "REQ-COVERAGE",
        "episode_id": "RADAR-V05-E-COVERAGE",
        "experiment_id": "EXP-COVERAGE",
        "type": kind,
        "hypothesis": "test hypothesis",
        "target_component": "upstream_component" if kind == "version_swap" else None,
        "changed_variable": "version" if kind == "version_swap" else None,
        "control": "old" if kind == "version_swap" else None,
        "candidate": "new" if kind == "version_swap" else None,
        "limits": {
            "network_policy": "denied",
            "timeout_seconds": 30,
            "memory_mb": 256,
            "output_mb": 10,
        },
    }


def test_investigation_build_validation_and_replay_lanes(tmp_path: Path) -> None:
    with pytest.raises(investigation.ValidationError):
        investigation.parse_aware("bad", "time")
    with pytest.raises(investigation.ValidationError):
        investigation.parse_aware("2020-01-01T00:00:00", "time")
    assert investigation.parse_aware("2020-01-01T00:00:00+00:00", "time").year == 2020
    assert investigation.canonical_digest({"a": 1}) == investigation.canonical_digest({"a": 1})

    record = _investigation_record()
    episode = investigation.build_episode(record, root=tmp_path)
    assert investigation.validate_episode(episode, root=tmp_path) == []
    view = investigation.build_candidate_view(episode)
    assert view["episode_id"] == episode["episode_id"]
    assert investigation._classify(record)[0] == "EXPERIMENTALLY_ATTRIBUTABLE"
    assert investigation._classify(
        _investigation_record(category="other")
    )[0] == "EXTERNALLY_DEPENDENT"
    safety = _investigation_record(corpus_kind="safety")
    assert investigation._classify(safety)[0] == "UNATTRIBUTABLE"
    no_visible = copy.deepcopy(record)
    no_visible["source_chain"][0]["available_after_cutoff"] = True
    no_visible["source_chain"][0]["snapshot_digest"] = ZERO_DIGEST
    no_visible["source_chain"][0]["published_at"] = "2020-03-02T00:00:00Z"
    built_no_visible = investigation.build_episode(no_visible, root=tmp_path)
    assert built_no_visible["observed_facts"][0]["evidence_ids"] == []

    assert not investigation.validate_experiment_request(_investigation_request(), root=tmp_path)
    assert investigation.validate_experiment_request(
        _investigation_request("version_swap"), root=tmp_path
    ) == []
    missing_pair = _investigation_request("version_swap")
    missing_pair["changed_variable"] = None
    missing_pair["candidate"] = None
    assert investigation.validate_experiment_request(missing_pair, root=tmp_path)
    rerun = _investigation_request("rerun")
    rerun["changed_variable"] = "bad"
    assert investigation.validate_experiment_request(rerun, root=tmp_path)
    invalid_episode = copy.deepcopy(episode)
    invalid_episode["tcut"] = "2019-01-01T00:00:00Z"
    invalid_episode["candidate_snapshot"]["visible_evidence_ids"] = ["hidden-1"]
    assert investigation.validate_episode(invalid_episode, root=tmp_path)

    oracle = investigation.ReplayOracle([episode, built_no_visible], root=tmp_path)
    base = _investigation_request()
    base["episode_id"] = episode["episode_id"]
    assert oracle.execute(base)["status"] == "AVAILABLE"
    version = _investigation_request("version_swap")
    version["episode_id"] = episode["episode_id"]
    assert oracle.execute(version)["result"]["outcome"] == "CANDIDATE_SPECIFIC"
    assert oracle.execute(dict(base, episode_id="RADAR-V05-E-UNKNOWN"))["status"] == "UNAVAILABLE"
    assert oracle.execute({"schema_version": "bad"})["status"] == "INVALID"
    for index in range(4):
        oracle.execute(dict(version, request_id=f"REQ-{index}"))
    assert oracle.execute(dict(version, request_id="REQ-LAST"))["error_codes"] == [
        "EXPERIMENT_BUDGET_EXHAUSTED"
    ]


def test_heuristic_investigator_terminal_lanes() -> None:
    view = {
        "episode_id": "RADAR-V05-E-COVERAGE",
        "plausible_components": investigation._component_candidates(),
    }

    def baseline(_request: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "status": "AVAILABLE",
            "result": {"outcome": "BASELINE_NOT_STABLE", "useful": False},
            "execution_evidence": [],
        }

    assert investigation.HeuristicInvestigator().run(view, baseline)["terminal"]["state"] == "BOUNDED_INCONCLUSIVE"

    calls = 0

    def supported(_request: Mapping[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "status": "AVAILABLE",
                "result": {
                    "outcome": "CONTROL_PASS_CANDIDATE_FAIL",
                    "useful": True,
                    "eliminated_hypotheses": ["environment_or_service"],
                },
                "execution_evidence": ["e1"],
            }
        return {
            "status": "AVAILABLE",
            "result": {
                "outcome": "CANDIDATE_SPECIFIC",
                "useful": True,
                "supported_component": "upstream_component",
                "candidate_induced": True,
            },
            "execution_evidence": ["e2"],
        }

    run = investigation.HeuristicInvestigator().run(view, supported)
    assert run["terminal"]["state"] == "CAUSALLY_ATTRIBUTED"
    assert run["substantive_experiments"] == 2

    invalid = investigation.HeuristicInvestigator().run(
        view, lambda _request: {"status": "INVALID", "result": {}}
    )
    assert invalid["terminal"]["state"] == "INVALID_INVESTIGATION"


def _v07_manifest(root: Path) -> dict[str, Any]:
    view = root / "view.json"
    view.write_text("{}", encoding="utf-8")
    workspace = root / "workspace"
    workspace.mkdir(exist_ok=True)
    (workspace / "source.txt").write_text("source", encoding="utf-8")
    artifact = root / "artifact.dat"
    artifact.write_bytes(b"artifact")
    digest = v07._directory_digest(workspace, root)
    artifact_digest = v07._sha256(artifact)
    command = ["python", "-c", "pass"]
    recipes = {
        capability: {"control_command": command, "candidate_command": command}
        for capability in v07.COMMON_CAPABILITIES
    }
    case = {
        "case_id": "CASE-1",
        "corpus_kind": "attribution",
        "platform": {
            "os": "linux",
            "architecture": "x86_64",
            "container_image": "registry/python@sha256:" + "a" * 64,
        },
        "candidate_view": "view.json",
        "candidate_view_digest": v07._sha256(view),
        "control": {
            "workspace": "workspace",
            "source_digest": digest,
            "revision": "abcdef1",
            "command": command,
            "environment": {"LANG": "C"},
        },
        "candidate": {
            "workspace": "workspace",
            "source_digest": digest,
            "revision": "abcdef2",
            "command": command,
            "environment": {"LANG": "C"},
        },
        "capability_recipes": recipes,
        "prepared_artifacts": [{"path": "artifact.dat", "digest": artifact_digest}],
    }
    return {
        "schema_version": v07.PROTOCOL_VERSION,
        "evaluation_policy": {
            "network": "denied",
            "gold_mounted": False,
            "historical_evidence_mounted": False,
            "artifact_policy": "local_only",
            "shell": False,
        },
        "capabilities": list(v07.COMMON_CAPABILITIES),
        "manifest_status": "SEALED",
        "cases": [case],
    }


def test_v07_manifest_validation_and_hermetic_executor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _v07_manifest(tmp_path)
    assert v07.validate_manifest(manifest, root=tmp_path) == []
    assert v07.digest_tree(tmp_path, ("*.json",)).startswith("sha256:")
    assert v07.manifest_digest(manifest).startswith("sha256:")
    assert v07._relative_path(tmp_path, "../escape", "path")[1]
    assert v07._argv(["python", "-c", "pass"], "cmd") == []
    assert v07._argv(["python", "--privileged"], "cmd")
    assert v07._contains_forbidden_runtime_value({"gold": "x"})
    assert v07.validate_request(
        {"schema_version": v07.PROTOCOL_VERSION, "request_id": "r", "episode_id": "e", "capability": "rerun"}
    ) == []
    assert v07.validate_request({"schema_version": "bad"})
    adapted = v07.adapt_frozen_request(
        {"type": "baseline_check", "request_id": "r", "episode_id": "e"}
    )
    assert adapted["capability"] == "rerun"
    with pytest.raises(ValueError):
        v07.adapt_frozen_request({"type": "unknown"})

    executor = v07.HermeticExecutor(manifest, root=tmp_path)
    assert executor.execute({"schema_version": "bad"})["status"] == "INVALID_REQUEST"
    assert executor.execute(
        {"schema_version": v07.PROTOCOL_VERSION, "request_id": "r", "episode_id": "missing", "capability": "rerun"}
    )["status"] == "EXECUTION_ERROR"
    def completed_side(*_args: object, **_kwargs: object) -> dict[str, Any]:
        return {
            "status": "COMPLETED",
            "returncode": 0,
            "output_digest": ZERO_DIGEST,
            "duration_ms": 1,
        }

    monkeypatch.setattr(executor, "_run_side", completed_side)
    result = executor.execute(
        {"schema_version": v07.PROTOCOL_VERSION, "request_id": "r", "episode_id": "CASE-1", "capability": "rerun"}
    )
    assert result["result"]["outcome"] == "NO_DISTINGUISHING_EFFECT"
    monkeypatch.setattr(
        executor,
        "_run_side",
        lambda _case, side, *_args, **_kwargs: {
            "status": "COMPLETED",
            "returncode": 0 if side == "control" else 1,
            "output_digest": ZERO_DIGEST,
            "duration_ms": 1,
        },
    )
    assert executor.execute(
        {"schema_version": v07.PROTOCOL_VERSION, "request_id": "r2", "episode_id": "CASE-1", "capability": "rerun"}
    )["result"]["outcome"] == "CANDIDATE_SPECIFIC"


def test_v07_run_side_preparation_gates_and_pilot_metrics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _v07_manifest(tmp_path)
    case = manifest["cases"][0]
    executor = v07.HermeticExecutor(manifest, root=tmp_path)
    monkeypatch.setattr(v07.shutil, "which", lambda _name: None)
    assert executor._run_side(case, "control", ["python"])["error"] == "DOCKER_NOT_FOUND"
    monkeypatch.setattr(v07.shutil, "which", lambda _name: "docker")
    cleanup = BoundedCapture(1, 0, ZERO_DIGEST, False, False, "")
    monkeypatch.setattr(v07, "run_bounded", lambda *_args, **_kwargs: cleanup)
    assert executor._run_side(case, "control", ["python"])["status"] == "EXECUTION_ERROR"
    assert v07.preparation_audit(tmp_path, tmp_path / "missing.json")["status"] == "BLOCKED_BY_EXECUTABILITY"
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{}", encoding="utf-8")
    assert v07.preparation_audit(tmp_path, malformed)["status"] == "BLOCKED_BY_EXECUTABILITY"
    valid_manifest_path = tmp_path / "manifest.json"
    valid_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert v07.preparation_audit(tmp_path, valid_manifest_path)["status"] == "BLOCKED_BY_EXECUTABILITY"
    freeze = v07.freeze_audit(tmp_path, "sha256:bad")
    assert freeze["digest_match"] is False

    cases = [
        {"case_id": "A", "corpus_kind": "attribution", "gold": {"candidate_induced": True, "should_abstain": False, "root_cause_component": "x", "action_owner_repository": "owner"}},
        {"case_id": "S", "corpus_kind": "safety", "gold": {"candidate_induced": None, "should_abstain": True, "root_cause_component": None, "action_owner_repository": None}},
    ]
    good_run = {
        "episode_id": "A",
        "terminal": {"state": "CAUSALLY_ATTRIBUTED", "candidate_induced": True, "root_cause_component": "x", "action_owner_repository": "owner"},
        "attempts": [{"useful": True}],
    }
    safe_run = {
        "episode_id": "S",
        "terminal": {"state": "BOUNDED_INCONCLUSIVE"},
        "attempts": [],
    }
    metrics = v07.evaluate_pilot(cases, [good_run, safe_run], [good_run], [safe_run], [safe_run])
    assert metrics["completed_runs"] == 2
    blocked = v07.v07_gates(metrics, {"status": "BLOCKED"}, {})
    assert blocked["decision"] == "BLOCKED_BY_EXECUTABILITY"
    failed = v07.v07_gates(metrics, {"status": "READY"}, {"digest_match": False})
    assert failed["decision"] == "KILL_RADAR_PRODUCT_THESIS"
    assert v07.case_gold(cases[0], "candidate_induced") is True


def test_historical_runtime_validation_and_docker_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    catalog, catalog_errors = historical._catalog_files(ROOT)
    assert catalog and not catalog_errors
    assert historical._safe_repo_path(ROOT, "src/radar_bench/v1_2.py")[1] is None
    assert historical._safe_repo_path(ROOT, "../escape")[1]
    assert historical._safe_name("safe-name") is True
    assert historical._safe_name("bad/name") is False
    assert historical._safe_container_path("/input", "/input") is True
    errors: list[str] = []
    assert historical._valid_command(["python", "-c", "pass"], "cmd", errors)
    historical._valid_command([], "cmd", errors)
    historical._valid_command(["bash"], "cmd", errors)
    historical._valid_command(["python", "a;b"], "cmd", errors)
    assert errors
    assert historical._bytes(None) == b""
    assert historical._bytes("text") == b"text"

    side_errors: list[str] = []
    historical._validate_side({}, "control", catalog, side_errors)
    historical._validate_side(
        {
            "case_id": "case",
            "control": {
                "packages": [{"name": "bad/name", "version": "", "wheel": "bad"}],
                "environment": {"bad-key": "line\n"},
                "command": ["bash"],
                "expected_exit": 999,
            },
        },
        "control",
        catalog,
        side_errors,
    )
    assert side_errors
    assert historical.validate_runtime_recipes(ROOT)["valid"] is True
    bad_runtime = tmp_path / historical.RUNTIME_RECIPES_RELATIVE
    bad_runtime.parent.mkdir(parents=True)
    bad_runtime.write_text("{}", encoding="utf-8")
    assert historical.validate_runtime_recipes(tmp_path)["valid"] is False
    assert historical._catalog_files(tmp_path)[1]

    capture = BoundedCapture(0, 3, ZERO_DIGEST, False, False, "ok", payload=b"ok")
    monkeypatch.setattr(historical, "run_bounded", lambda *_args, **_kwargs: capture)
    assert historical._run_docker(["docker", "info"], timeout=1)["returncode"] == 0
    monkeypatch.setattr(
        historical,
        "run_bounded",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")),
    )
    assert historical._run_docker(["docker"], timeout=1)["error_type"] == "OSError"
    monkeypatch.setattr(historical, "run_bounded", lambda *_args, **_kwargs: capture)
    assert historical._ensure_base_image("docker", "image")[0] is True
    sequence = iter(
        [
            {"returncode": 1},
            {"returncode": 1},
        ]
    )
    monkeypatch.setattr(historical, "_run_docker", lambda *_args, **_kwargs: next(sequence))
    assert historical._ensure_base_image("docker", "image")[0] is False
    sequence = iter([{"returncode": 1}, {"returncode": 0}, {"returncode": 1}])
    monkeypatch.setattr(historical, "_run_docker", lambda *_args, **_kwargs: next(sequence))
    assert historical._ensure_base_image("docker", "image")[2] == "BASE_IMAGE_UNAVAILABLE"
    monkeypatch.setattr(
        historical,
        "_run_docker",
        lambda *_args, **_kwargs: {"returncode": 0, "_output": b"Python 3.11.0\n"},
    )
    assert historical._exact_python("docker", "image", "3.11.0")[0] is True
    assert historical._exact_python("docker", "image", "3.12.0")[1] == "BASE_IMAGE_RUNTIME_MISMATCH"
    monkeypatch.setattr(
        historical,
        "_run_docker",
        lambda *_args, **_kwargs: {"returncode": 1, "_output": b""},
    )
    assert historical._exact_python("docker", "image", "3.11.0")[1] == "BASE_IMAGE_RUNTIME_UNAVAILABLE"

    recipe = json.loads(
        (ROOT / historical.RUNTIME_RECIPES_RELATIVE).read_text(encoding="utf-8")
    )["recipes"][0]
    recipe["_document_build"] = json.loads(
        (ROOT / historical.RUNTIME_RECIPES_RELATIVE).read_text(encoding="utf-8")
    )["build"]
    assert "FROM" in historical._dockerfile(recipe, "control", ["demo.whl"])
    assert historical._mount(tmp_path, "/input", True).endswith(",readonly")
    assert historical._container_name("case", "control", "run").startswith("radar-bench-v11-")
    assert historical._volume_name("case").startswith("radar-bench-v11-input-")


def test_historical_runtime_execution_and_cleanup_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ok = {"returncode": 0, "_output": b""}
    monkeypatch.setattr(historical, "_run_docker", lambda *_args, **_kwargs: ok)
    assert historical._remove_container("docker", "name")["cleanup_verified"] is True
    assert historical._remove_volume("docker", "volume")["cleanup_verified"] is True
    assert historical._remove_image("docker", "image")["cleanup_verified"] is True
    present = {"returncode": 0, "_output": b"name\n"}
    monkeypatch.setattr(historical, "_run_docker", lambda *_args, **_kwargs: present)
    assert historical._remove_container("docker", "name")["cleanup_verified"] is False

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    monkeypatch.setattr(historical, "_remove_container", lambda *_args: {"cleanup_verified": True})
    monkeypatch.setattr(historical, "_run_docker", lambda *_args, **_kwargs: {"returncode": 0, "_output": b""})
    result = historical._run_case_side(
        "docker", "image", "control", ["python"], {}, input_dir, case_id="case"
    )
    assert result["side"] == "control"
    deferred = historical._run_case_side(
        "docker", "image", "control", ["python"], {}, input_dir, case_id="case", cleanup_after=False
    )
    assert deferred["container_cleanup_deferred"] is True
    monkeypatch.setattr(historical, "_remove_container", lambda *_args: {"cleanup_verified": False})
    assert historical._run_case_side(
        "docker", "image", "control", ["python"], {}, input_dir, case_id="case"
    )["error_type"] == "PREEXISTING_CONTAINER_CLEANUP_UNVERIFIED"

    artifact_root = tmp_path / "artifacts"
    bundle = artifact_root / "bundle"
    bundle.mkdir(parents=True)
    wheel = _wheel_bytes()
    (bundle / "demo.whl").write_bytes(wheel)
    recipe = {
        "artifacts": ["bundle"],
        "control": {"packages": [{"wheel": "demo.whl"}]},
        "_reproducer_path": str(ROOT / "src/radar_bench/resources/corpus/v1.0.1/decisive-v1.1/reproducers/a01_pickle.py"),
        "platform": {"container_image": "image"},
        "_document_build": {"install_command": ["python", "-m", "pip", "install"]},
        "reproducer": "reproducer.py",
    }
    context = tmp_path / "context"
    context.mkdir()
    monkeypatch.setattr(historical, "_run_docker", lambda *_args, **_kwargs: {"returncode": 1, "_output": b""})
    tag, error = historical._build_side("docker", recipe, "control", artifact_root, context)
    assert tag and error == "IMAGE_BUILD_FAILED"
    (bundle / "demo.whl").unlink()
    context_missing = tmp_path / "context-missing"
    context_missing.mkdir()
    assert historical._build_side("docker", recipe, "control", artifact_root, context_missing)[1] == "ARTIFACT_UNAVAILABLE"
    assert historical.reconstruct_historical_cases(ROOT)["status"] == "BLOCKED"


def test_historical_reconstruction_ready_path_with_fake_docker(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        historical,
        "verify_artifacts",
        lambda *_args, **_kwargs: {"status": "READY", "errors": [], "bundles": []},
    )
    monkeypatch.setattr(historical.shutil, "which", lambda _name: "docker")
    monkeypatch.setattr(
        historical,
        "inspect_docker_runtime",
        lambda **_kwargs: SimpleNamespace(supported=True, reason=None),
    )
    monkeypatch.setattr(historical, "_ensure_base_image", lambda *_args: (True, False, None))
    monkeypatch.setattr(historical, "_exact_python", lambda *_args: (True, None))
    monkeypatch.setattr(historical, "_build_side", lambda *_args: ("image-tag", None))
    monkeypatch.setattr(historical, "_run_docker", lambda *_args, **_kwargs: {"returncode": 0, "_output": b""})
    monkeypatch.setattr(historical, "_copy_declared_outputs", lambda *_args: (True, None, {"observed": []}))
    monkeypatch.setattr(historical, "_remove_container", lambda *_args: {"cleanup_verified": True})
    monkeypatch.setattr(historical, "_remove_volume", lambda *_args: {"cleanup_verified": True})
    monkeypatch.setattr(historical, "_remove_image", lambda *_args: {"cleanup_verified": True})

    def fake_side(_docker: str, _image: str, side: str, _command: list[str], _environment: Mapping[str, str], _input_dir: Path, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("preparation"):
            return {"returncode": 0, "container_name": "prep-container"}
        case_id = str(kwargs.get("case_id"))
        return {"returncode": 139 if case_id.endswith("A05") and side == "candidate" else 0 if side == "control" else 1, "output_digest": ZERO_DIGEST}

    monkeypatch.setattr(historical, "_run_case_side", fake_side)
    result = historical.reconstruct_historical_cases(ROOT, ROOT / "artifacts/external/decisive-v1.1")
    assert result["status"] == "READY"
    assert len(result["cases"]) == 5


def test_release_audit_and_blocked_publication_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact_root = ROOT / "artifacts/external/decisive-v1.1"
    audit = release.validate_decisive_suite(ROOT, artifact_root=artifact_root)
    assert audit["valid"] is True
    suite = release.load_suite(ROOT)
    base = (ROOT / release.SUITE_RELATIVE).parent
    for entry in suite["historical_cases"]:
        case_audit = release._audit_historical_case(ROOT, entry, base, artifact_root)
        assert case_audit["valid"] is True
        assert case_audit["status"] in {"READY", "BLOCKED"}
    assert release._artifact_status({}, artifact_root=artifact_root)["available"] is False
    assert release._artifact_status({"artifact_bundle": {"bundle_id": "../bad"}}, artifact_root=artifact_root)["available"] is False
    assert release._audit_opacity([ROOT], [ROOT / "missing"])["valid"] is False
    assert release._resolve_inside(ROOT, ROOT, "../escape")[1]
    assert release._empty_metric(1)["denominator"] == 1
    assert len(release._empty_metrics()) == 11
    blocked_cases = release._blocked_cases(audit, "ARTIFACT_UNAVAILABLE")
    assert len(blocked_cases) == 25

    invalid_legacy = release._archived_decisive_suite_legacy(tmp_path)
    assert invalid_legacy["status"] == "INVALID"
    valid_runtime = SimpleNamespace(
        available=True,
        supported=False,
        reason="PLATFORM_UNAVAILABLE",
        engine_os="windows",
        engine_architecture="x86_64",
        as_dict=lambda: {"available": True, "supported": False},
    )
    monkeypatch.setattr(release, "inspect_docker_runtime", lambda: valid_runtime)
    legacy = release._archived_decisive_suite_legacy(ROOT, artifact_root=artifact_root)
    assert legacy["status"] == "BLOCKED"
    assert legacy["blockers"] in (["ARTIFACT_UNAVAILABLE"], ["PLATFORM_UNAVAILABLE"])
    real_validate = release.validate_decisive_suite
    monkeypatch.setattr(
        release,
        "validate_decisive_suite",
        lambda *_args, **_kwargs: {
            "valid": True,
            "historical": [{"case_id": case_id, "block_reason": None} for case_id in release.HISTORICAL_IDS],
            "safety": {"count": 20},
        },
    )
    runtime_blocked = release._archived_decisive_suite_legacy(ROOT)
    assert runtime_blocked["blockers"] == ["PLATFORM_UNAVAILABLE"]
    monkeypatch.setattr(release, "validate_decisive_suite", real_validate)
    evaluated = release.evaluate_decisive_suite(ROOT, artifact_root=artifact_root)
    assert evaluated["status"] == "BLOCKED"
    output = tmp_path / "evaluation.json"
    written = release.write_evaluation(ROOT, output)
    assert output.is_file()
    assert written["status"] == "BLOCKED"
    assert release.inspect_case(ROOT, "RADAR-V07-T01")["runtime_visible"] is True
    with pytest.raises(ValueError):
        release.inspect_case(ROOT, "RADAR-V07-T99")


def test_release_legacy_completed_negative_conclusion(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_root = ROOT / "artifacts/external/decisive-v1.1"
    runtime = SimpleNamespace(
        available=True,
        supported=True,
        reason=None,
        engine_os="linux",
        engine_architecture="x86_64",
    )
    monkeypatch.setattr(release, "inspect_docker_runtime", lambda **_kwargs: runtime)
    monkeypatch.setattr(
        release,
        "reconstruct_historical_cases",
        lambda *_args, **_kwargs: {"status": "READY", "network_used": False, "cases": []},
    )
    metrics = {
        "lanes": {
            "static-v0.4": {"metrics": {"historical_positive_resolution": {"numerator": 4}}},
            "agentic-v0.5-frozen": {
                "metrics": {
                    "historical_positive_resolution": {"numerator": 1},
                    "safety_abstention_recall": {"numerator": 20},
                }
            },
        },
        "mandatory_case_gates": {
            "scikit-learn-30512-resolves-to-scipy": False,
            "pandas-45601-keeps-semantic-ambiguity-open": True,
        },
    }

    class FakeHarness:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def run(self, _runtime: Mapping[str, Any]) -> dict[str, Any]:
            return {"status": "COMPLETED", "metrics": metrics}

    monkeypatch.setattr(release, "CanonicalHarness", FakeHarness)
    monkeypatch.setattr(
        release,
        "validate_decisive_suite",
        lambda *_args, **_kwargs: {
            "valid": True,
            "historical": [{"case_id": case_id, "block_reason": None} for case_id in release.HISTORICAL_IDS],
            "safety": {"count": 20},
        },
    )
    result = release._archived_decisive_suite_legacy(ROOT, artifact_root=artifact_root)
    assert result["status"] == "COMPLETED"
    assert result["release_ready"] is True
    assert result["decision"] == "CANONICAL_NEGATIVE_REPRODUCED"


def test_v12_executor_recipe_argv_and_cleanup_lanes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(ValueError):
        executor_module.normalize_python_command([], interpreter="python")
    with pytest.raises(ValueError):
        executor_module.normalize_python_command(["bash", "script.py"])
    with pytest.raises(ValueError):
        executor_module.normalize_python_command(["python"])
    assert executor_module.normalize_python_command(["python3", "script.py"], interpreter="python") == [
        "python",
        "script.py",
    ]
    artifact_root = tmp_path / "external" / "decisive-v1.2"
    (artifact_root / "pandas-55137-wheelhouse").mkdir(parents=True)
    executor = executor_module.V12ExperimentExecutor(
        ROOT,
        episode_to_case={"episode": "RADAR-V07-A01", "safety": "RADAR-V07-T01"},
        artifact_root=artifact_root,
    )
    runtime = executor.recipes["RADAR-V07-A01"]
    assert executor._workspace(runtime, "control") is not None
    assert executor._workspace({"control": {"workspace": "../bad"}}, "control") is None
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    command = ["python", "-c", "pass"]
    assert executor._docker_argv(runtime, "control", command, input_dir) is not None
    assert executor._docker_argv({"platform": {}}, "control", command, input_dir) is None
    assert executor._docker_argv(runtime, "control", command, input_dir, site_volume="bad") is None
    bad_env = copy.deepcopy(runtime)
    bad_env["control"]["environment"]["LANG"] = "bad\nvalue"
    assert executor._docker_argv(bad_env, "control", command, input_dir) is None
    assert executor._command_for(runtime, "control", {"capability": "inspect_environment"})[0] == "python"
    assert executor._command_for(runtime, "control", {"capability": "inspect_dependency_graph"})[0] == "python"
    assert executor._command_for(runtime, "control", {"capability": "run_minimal_test", "parameters": {}}) is None
    assert executor._command_for(runtime, "control", {"capability": "run_minimal_test", "parameters": {"test_id": "sealed-reproducer"}})
    assert executor._command_for(runtime, "control", {"capability": "unknown", "parameters": {}})
    no_artifacts = copy.deepcopy(runtime)
    no_artifacts.pop("artifacts", None)
    assert executor._command_for(no_artifacts, "control", {"capability": "change_dependency_version"}) is None
    plain = executor._installing_command(no_artifacts, "control", command, {"capability": "rerun"})
    assert plain == command
    assert executor._requires_site_volume(runtime, "control") is True
    assert executor._requires_site_volume(no_artifacts, "control") is False
    changed = executor._installing_command(
        runtime,
        "candidate",
        command,
        {"capability": "change_dependency_version", "parameters": {"target_component": "pandas", "version": "2.1.0"}},
    )
    assert changed and changed[0] == "python"
    assert executor._installing_command(
        runtime,
        "candidate",
        command,
        {"capability": "change_dependency_version", "parameters": {}},
    ) is None
    assert executor._installing_command(
        runtime,
        "candidate",
        command,
        {"capability": "change_dependency_version", "parameters": {"target_component": "missing", "version": "1"}},
    ) is None

    first = BoundedCapture(1, 0, ZERO_DIGEST, False, False, "")
    absent = BoundedCapture(1, 0, ZERO_DIGEST, False, False, "no such object")
    monkeypatch.setattr(executor_module.shutil, "which", lambda _name: "docker")
    monkeypatch.setattr(executor_module, "run_bounded", lambda *_args, **_kwargs: absent)
    assert executor._cleanup_container("container")["cleanup_verified"] is True
    assert executor._cleanup_volume("volume")["cleanup_verified"] is False
    monkeypatch.setattr(executor_module, "run_bounded", lambda *_args, **_kwargs: first)
    assert executor._cleanup_container("container")["cleanup_verified"] is False
    assert executor._copy_volume_to_staging({}, "volume", tmp_path) is None
    staging = tmp_path / "staging"
    staging.mkdir()
    assert executor._audit_preparation_output(staging, [])[0] is True
    nested = staging / "nested"
    nested.mkdir()
    assert executor._audit_preparation_output(staging, [])[1] == "PREPARATION_OUTPUT_INVALID"
    assert executor._capture_is_complete(BoundedCapture(0, 0, ZERO_DIGEST, False, False, "")) is True
    assert executor._capture_is_complete(BoundedCapture(None, 0, ZERO_DIGEST, False, False, "")) is False
    receipt = executor._evaluator_receipt(
        {"capability": "inspect_environment"},
        BoundedCapture(0, 1, "sha256:" + "1" * 64, False, False, ""),
        BoundedCapture(0, 1, "sha256:" + "2" * 64, False, False, ""),
    )
    assert receipt["useful"] is True


def test_v12_executor_call_preparation_and_observation_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executor = executor_module.V12ExperimentExecutor(
        ROOT,
        episode_to_case={"episode": "RADAR-V07-T01", "historical": "RADAR-V07-A01"},
    )
    request = {"capability": "rerun", "parameters": {}}
    assert executor("unknown", request)["observation"]["status"] == "EPISODE_NOT_BOUND"
    monkeypatch.setattr(executor_module.shutil, "which", lambda _name: None)
    assert executor("episode", request)["observation"]["status"] == "DOCKER_UNAVAILABLE"
    monkeypatch.setattr(executor_module.shutil, "which", lambda _name: "docker")
    capture = BoundedCapture(0, 1, ZERO_DIGEST, False, False, "ok")
    monkeypatch.setattr(executor, "_run_side", lambda *_args, **_kwargs: capture)
    assert executor("episode", request)["status"] == "COMPLETED"
    invalid = executor("episode", {"capability": "run_minimal_test", "parameters": {}})
    assert invalid["status"] == "INVALID_REQUEST"
    unsupported = executor("episode", {"capability": "change_dependency_version", "parameters": {}})
    assert unsupported["status"] == "UNSUPPORTED_EXPERIMENT"

    historical_artifact_root = tmp_path / "external-historical" / "decisive-v1.2"
    (historical_artifact_root / "pandas-55137-wheelhouse").mkdir(parents=True)
    historical_executor = executor_module.V12ExperimentExecutor(
        ROOT,
        episode_to_case={"historical": "RADAR-V07-A01"},
        artifact_root=historical_artifact_root,
    )
    historical_executor.artifact_status = {"status": "READY"}
    monkeypatch.setattr(executor_module, "run_bounded", lambda *_args, **_kwargs: capture)
    monkeypatch.setattr(historical_executor, "_run_side", lambda *_args, **_kwargs: capture)
    def copy_staging(_runtime: Mapping[str, Any], _volume: str, staging: Path) -> BoundedCapture:
        (staging / "old_pandas.pkl").write_bytes(b"x")
        return capture

    monkeypatch.setattr(historical_executor, "_copy_volume_to_staging", copy_staging)
    monkeypatch.setattr(historical_executor, "_cleanup_volume", lambda _name: {"cleanup_verified": True})
    assert historical_executor("historical", request)["status"] == "COMPLETED"


def test_v12_external_protocol_error_state_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packets = [
        v12.CandidatePacket(f"episode-{index}", {}, tuple(sorted(v12.CAPABILITIES)))
        for index in range(len(v12.ALL_CASE_IDS))
    ]
    protocol = v12.ExternalCandidateProtocol(
        "registry/python@sha256:" + "a" * 64,
        ["python", "-c", "pass"],
        working_directory=tmp_path,
    )

    def run_frames(
        frames: list[bytes],
        *,
        stdin_available: bool = True,
        config_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        output_read, output_write = os.pipe()
        error_read, error_write = os.pipe()
        def writer() -> None:
            for frame in frames:
                os.write(output_write, frame + b"\n")
                threading.Event().wait(0.001)
            os.close(output_write)
            os.close(error_write)

        threading.Thread(target=writer, daemon=True).start()

        class Stream:
            def __init__(self, descriptor: int) -> None:
                self.descriptor = descriptor

            def fileno(self) -> int:
                return self.descriptor

        class Stdin:
            def write(self, value: bytes) -> int:
                return len(value)

            def flush(self) -> None:
                return None

            def close(self) -> None:
                return None

        class Process:
            stdin = Stdin() if stdin_available else None
            stdout = Stream(output_read)
            stderr = Stream(error_read)
            returncode: int | None = None

            def poll(self) -> int | None:
                return self.returncode

            def wait(self, **_kwargs: object) -> int:
                self.returncode = 0
                return 0

            def kill(self) -> None:
                self.returncode = -9

        process = Process()
        monkeypatch.setattr(v12.subprocess, "Popen", lambda *_args, **_kwargs: process)
        monkeypatch.setattr(
            protocol,
            "_actual_container_config",
            lambda: list(config_errors or []),
        )
        monkeypatch.setattr(protocol, "_cleanup_container", lambda: True)
        result = protocol.run(packets)
        os.close(output_read)
        os.close(error_read)
        return result

    valid_prediction = _prediction()
    final_frames = [
        json.dumps({
            "schema_version": v12.V12_PROTOCOL_VERSION,
            "message": "final_prediction",
            "episode_id": packet.episode_id,
            "prediction": valid_prediction,
        }).encode()
        for packet in packets
    ]
    request_frame = json.dumps({
        "schema_version": v12.V12_PROTOCOL_VERSION,
        "message": "experiment_request",
        "episode_id": packets[0].episode_id,
        "request_id": "request",
        "capability": "rerun",
        "parameters": {},
    }).encode()
    noisy = [
        b"not-json",
        b"[]",
        json.dumps({"message": "final_prediction", "episode_id": "unknown", "prediction": valid_prediction}).encode(),
        json.dumps({"schema_version": v12.V12_PROTOCOL_VERSION, "message": "final_prediction", "episode_id": packets[0].episode_id, "prediction": {}}).encode(),
        request_frame,
        request_frame,
            final_frames[0],
            final_frames[0],
            *final_frames[1:],
    ]
    result = run_frames(noisy)
    assert result["status"] == "BLOCKED"
    assert "CANDIDATE_NON_JSON_OUTPUT" in result["errors"]
    assert "DUPLICATE_REQUEST_ID" in result["errors"]
    assert "DUPLICATE_TERMINAL_RESULT" in result["errors"]

    config_result = run_frames([], config_errors=["bad config"])
    assert config_result["errors"][0] == "CANDIDATE_ACTUAL_CONFIG_INVALID"
    monkeypatch.setattr(protocol, "_actual_container_config", lambda: [])
    stdin_result = run_frames([], stdin_available=False)
    assert "CANDIDATE_PROCESS_STDIN_UNAVAILABLE" in stdin_result["errors"]


def test_config_materialization_revalidates_corrupt_destinations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RADAR_BENCH_CACHE", str(tmp_path / "cache"))
    first = config.package_resource_root()
    assert config.package_resource_root() == first
    manifest = first / "resource-manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="destination already conflicts"):
        config.package_resource_root()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("RADAR_BENCH_CACHE")
    # Simulate the Windows branch without mutating the process-wide os module;
    # pathlib uses that same module to select its host path implementation.
    monkeypatch.setattr(
        config,
        "os",
        SimpleNamespace(name="nt", environ=os.environ, urandom=os.urandom),
    )
    assert config.cache_root().parent == (tmp_path / "local")
    assert config.secrets_token()


def test_cli_error_and_v12_command_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert cli.command_validate(
        type("Args", (), {"suite": v12.V12_SUITE_ID, "evaluator_bundle": str(ROOT / "evaluator/decisive-v1.2/evaluator-bundle.json"), "artifact_root": None})()
    ) in {cli.EXIT_OK, cli.EXIT_INVALID}
    assert cli.command_inspect_case(type("Args", (), {"case_id": "RADAR-V07-A01"})()) == 0
    assert cli.command_inspect_case(type("Args", (), {"case_id": "bad"})()) == cli.EXIT_INVALID
    output = tmp_path / "v12.json"
    monkeypatch.setattr(cli, "evaluate_v12", lambda *_args, **_kwargs: {"status": "BLOCKED"})
    assert cli.command_evaluate(
        type("Args", (), {"suite": v12.V12_SUITE_ID, "artifact_root": None, "candidate_image": None, "candidate_argv": None, "evaluator_bundle": None, "output": str(output)})()
    ) == cli.EXIT_EXTERNAL
    assert output.is_file()
    monkeypatch.setattr(cli, "fetch_artifacts", lambda *_args: {"status": "READY"})
    monkeypatch.setattr(cli, "verify_artifacts", lambda *_args: {"status": "BLOCKED"})
    assert cli.command_artifacts(type("Args", (), {"action": "fetch", "suite": "decisive-v1.1", "output_root": str(tmp_path)})()) == 0
    assert cli.command_artifacts(type("Args", (), {"action": "verify", "suite": "decisive-v1.1", "artifact_root": str(tmp_path)})()) == cli.EXIT_EXTERNAL
    valid = _completed_result()
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(valid), encoding="utf-8")
    assert cli.command_verify_results(type("Args", (), {"path": str(result_path)})()) == 0
    result_path.write_text("[]", encoding="utf-8")
    assert cli.command_verify_results(type("Args", (), {"path": str(result_path)})()) == cli.EXIT_INVALID


def test_provider_and_inference_packet_boundaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(provider_module.SecurityError):
        provider_module.SubprocessProvider([])
    with pytest.raises(provider_module.SecurityError):
        provider_module.SubprocessProvider(["python", "-c", "pass"])
    with pytest.raises(provider_module.SecurityError):
        provider_module.SubprocessProvider(["provider"], timeout=0)
    capture = BoundedCapture(0, 2, ZERO_DIGEST, False, False, "{}", payload=b"{}")
    monkeypatch.setattr(provider_module, "run_bounded", lambda *_args, **_kwargs: capture)
    assert provider_module.SubprocessProvider(["provider"]).predict({}) == {}
    for replacement, error in [
        (BoundedCapture(0, 0, ZERO_DIGEST, False, True, ""), TimeoutError),
        (BoundedCapture(0, 0, ZERO_DIGEST, True, False, ""), provider_module.SecurityError),
        (BoundedCapture(1, 0, ZERO_DIGEST, False, False, ""), RuntimeError),
        (BoundedCapture(0, 0, ZERO_DIGEST, False, False, "x", payload=b"[]"), TypeError),
    ]:
        monkeypatch.setattr(provider_module, "run_bounded", lambda *_args, value=replacement, **_kwargs: value)
        with pytest.raises(error):
            provider_module.SubprocessProvider(["provider"]).predict({})
    with pytest.raises(provider_module.SecurityError):
        provider_module.SubprocessProvider(["provider"]).predict({"x": "x" * provider_module.MAX_INPUT_BYTES})
    packet_root = tmp_path / "candidate"
    (packet_root / "input").mkdir(parents=True)
    (packet_root / "input/snapshot.json").write_text('{"value": 1}', encoding="utf-8")
    assert inference_packet(packet_root, allowed_root=tmp_path)["value"] == 1
    with pytest.raises(ValueError):
        inference_packet(tmp_path / "gold", allowed_root=tmp_path)
    with pytest.raises(ValueError):
        inference_packet(ROOT, allowed_root=tmp_path)


def test_artifact_defensive_validation_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    oversized = tmp_path / "oversized.json"
    oversized.write_text("x" * (artifacts.MAX_JSON_BYTES + 1), encoding="utf-8")
    with pytest.raises(artifacts.ArtifactContractError, match="size limit"):
        artifacts._read_json(oversized)
    non_object = tmp_path / "array.json"
    non_object.write_text("[]", encoding="utf-8")
    with pytest.raises(artifacts.ArtifactContractError, match="object required"):
        artifacts._read_json(non_object)
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{", encoding="utf-8")
    with pytest.raises(artifacts.ArtifactContractError, match="cannot read"):
        artifacts._read_json(invalid_json)
    with pytest.raises(artifacts.ArtifactContractError):
        artifacts._safe_relative(tmp_path, str(tmp_path / "absolute"))
    assert not artifacts._safe_name("")
    assert not artifacts._safe_name("a/b.whl")
    assert not artifacts._valid_digest(None)

    unsafe_archive = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(unsafe_archive, "w") as archive:
        archive.writestr("../escape.txt", "x")
        archive.writestr("folder\\escape.txt", "x")
    assert artifacts._validate_archive(unsafe_archive)

    invalid_urls = [
        "http://pypi.org/pypi/demo/1.0/json",
        "https://evil.example/pypi/demo/1.0/json",
        "https://user:p@pypi.org/pypi/demo/1.0/json",
        "https://pypi.org:443/pypi/demo/1.0/json",
        "https://pypi.org/pypi/demo/1.0/json?x=1",
        "https://pypi.org/pypi/demo/1.0/json#fragment",
        "https://pypi.org/pypi/demo/1.0/\njson",
    ]
    assert all(not artifacts._approved_https_url(value, artifacts.PYPI_API_HOST) for value in invalid_urls)
    assert not artifacts._approved_file_url(
        f"https://{artifacts.PYPI_FILE_HOST}/packages/%zz/other.whl",
        "demo-1.0-py3-none-any.whl",
    )
    with pytest.raises(artifacts.ArtifactContractError):
        artifacts._pypi_project_version("demo.whl")

    class Remote:
        def __init__(self, payload: bytes, final_url: str, length: str | None = None) -> None:
            self.payload = payload
            self.final_url = final_url
            self.headers = {} if length is None else {"Content-Length": length}

        def __enter__(self) -> "Remote":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def geturl(self) -> str:
            return self.final_url

        def read(self, size: int) -> bytes:
            value, self.payload = self.payload[:size], self.payload[size:]
            return value

    metadata_url = "https://pypi.org/pypi/demo/1.0/json"
    file_url = f"https://{artifacts.PYPI_FILE_HOST}/packages/d/demo-1.0-py3-none-any.whl"
    monkeypatch.setattr(
        artifacts,
        "urlopen",
        lambda *_args, **_kwargs: Remote(b"{}", "https://evil.example/redirect"),
    )
    with pytest.raises(artifacts.ArtifactContractError, match="unable"):
        artifacts._read_remote_json(metadata_url)
    monkeypatch.setattr(
        artifacts,
        "urlopen",
        lambda *_args, **_kwargs: Remote(b"{}", metadata_url, str(artifacts.MAX_JSON_BYTES + 1)),
    )
    with pytest.raises(artifacts.ArtifactContractError, match="unable"):
        artifacts._read_remote_json(metadata_url)
    monkeypatch.setattr(
        artifacts,
        "urlopen",
        lambda *_args, **_kwargs: Remote(b"not-json", metadata_url),
    )
    with pytest.raises(artifacts.ArtifactContractError, match="not valid JSON"):
        artifacts._read_remote_json(metadata_url)
    monkeypatch.setattr(
        artifacts,
        "urlopen",
        lambda *_args, **_kwargs: Remote(b"[]", metadata_url),
    )
    with pytest.raises(artifacts.ArtifactContractError, match="not an object"):
        artifacts._read_remote_json(metadata_url)
    monkeypatch.setattr(
        artifacts,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
    )
    with pytest.raises(artifacts.ArtifactContractError, match="unable"):
        artifacts._read_remote_json(metadata_url)

    cache: dict[str, str] = {}
    monkeypatch.setattr(artifacts, "_read_remote_json", lambda _url: {})
    with pytest.raises(artifacts.ArtifactContractError, match="no files"):
        artifacts._source_url("demo-1.0-py3-none-any.whl", cache)
    monkeypatch.setattr(
        artifacts,
        "_read_remote_json",
        lambda _url: {"urls": [{"filename": "other.whl", "url": file_url}]},
    )
    with pytest.raises(artifacts.ArtifactContractError, match="unavailable"):
        artifacts._source_url("demo-1.0-py3-none-any.whl", {})
    monkeypatch.setattr(
        artifacts,
        "_read_remote_json",
        lambda _url: {"urls": [{"filename": "demo-1.0-py3-none-any.whl", "url": "https://evil.example/demo-1.0-py3-none-any.whl"}]},
    )
    with pytest.raises(artifacts.ArtifactContractError, match="unapproved"):
        artifacts._source_url("demo-1.0-py3-none-any.whl", {})

    payload = _wheel_bytes()
    expected = artifacts.ArtifactFile(
        "demo-1.0-py3-none-any.whl", "sha256:" + hashlib.sha256(payload).hexdigest(), len(payload)
    )
    destination = tmp_path / expected.name
    with pytest.raises(artifacts.ArtifactContractError, match="approved"):
        artifacts._download("https://evil.example/file.whl", destination, expected)
    monkeypatch.setattr(
        artifacts,
        "urlopen",
        lambda *_args, **_kwargs: Remote(payload, file_url, str(len(payload) + 1)),
    )
    with pytest.raises(artifacts.ArtifactContractError, match="exceeds"):
        artifacts._download(file_url, destination, expected)
    monkeypatch.setattr(
        artifacts,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
    )
    with pytest.raises(artifacts.ArtifactContractError, match="unable to download"):
        artifacts._download(file_url, destination, expected)
    wrong = artifacts.ArtifactFile(expected.name, ZERO_DIGEST, len(payload))
    monkeypatch.setattr(artifacts, "urlopen", lambda *_args, **_kwargs: Remote(payload, file_url))
    with pytest.raises(artifacts.ArtifactContractError, match="verification failed"):
        artifacts._download(file_url, destination, wrong)
    bad_payload = b"not-a-wheel"
    bad_expected = artifacts.ArtifactFile(
        expected.name, "sha256:" + hashlib.sha256(bad_payload).hexdigest(), len(bad_payload)
    )
    monkeypatch.setattr(artifacts, "urlopen", lambda *_args, **_kwargs: Remote(bad_payload, file_url))
    with pytest.raises(artifacts.ArtifactContractError, match="archive validation"):
        artifacts._download(file_url, destination, bad_expected)


def test_v12_helper_and_isolation_boundary_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert len(v12.empty_v12_metrics()) == len(v12.METRICS)
    with pytest.raises(ValueError):
        v12.generate_episode_ids(["unknown"])
    assert v12.canonicalize_case_order([{"episode_id": "b"}, {}])[0].get("episode_id") is None

    candidate = _candidate()
    invalid_evidence = copy.deepcopy(candidate)
    for key in ("context", "reproducer", "failure_observation", "control_manifest", "candidate_manifest", "package_environment_diff", "dependency_graph", "platform"):
        invalid_evidence["cases"][0]["evidence"][key] = None
    invalid_evidence["cases"][0]["evidence"]["source_location_evidence"] = [1]
    invalid_evidence["cases"][0]["evidence"]["provenance_references"] = [1]
    assert v12.validate_candidate_document(invalid_evidence)
    shape = copy.deepcopy(candidate)
    shape["cases"][0]["evidence"] = dict(shape["cases"][0]["evidence"])
    shape["cases"][0]["evidence"].pop("platform")
    assert v12.metadata_shape_classifier_audit(shape)["status"] == "BLOCKED"
    assert v12.validate_experiment_request({"capability": "unknown", "parameters": {}})
    assert v12.validate_experiment_request({"capability": "rerun", "parameters": {"extra": 1}})
    assert v12.validate_experiment_request({"capability": "run_minimal_test", "parameters": {}})
    assert v12.validate_experiment_request({"capability": "run_minimal_test", "parameters": {"test_id": "other"}})
    assert v12.validate_experiment_request({"capability": "rerun", "parameters": {"command": 1}})

    ledger = v12.ExperimentLedger(max_experiments=1)
    request = {"capability": "rerun", "parameters": {}}
    receipt = {"available": True, "fresh": True, "useful": True, "cleanup_verified": True}
    assert ledger.run(request, lambda _request: {"status": "AVAILABLE", "evaluator_receipt": receipt})["fresh"]
    assert ledger.run(request, lambda _request: {})["error_codes"] == ["EXPERIMENT_BUDGET_EXHAUSTED"]
    failed = v12.ExperimentLedger().run(request, lambda _request: (_ for _ in ()).throw(RuntimeError("boom")))
    assert failed["response"]["status"] == "EXECUTION_ERROR"
    invalid = v12.ExperimentLedger().run({"capability": "rerun", "parameters": {"cache": True}}, lambda _request: {})
    assert invalid["valid"] is False
    with pytest.raises(ValueError):
        v12.ExperimentLedger().run(request, lambda _request: {"evaluator_receipt": {"cache_hit": True}})

    valid_mapping = dict(_evaluator()["record_case_mapping"])
    duplicate_mapping = dict(valid_mapping)
    duplicate_mapping["record-002"] = duplicate_mapping["record-001"]
    assert v12.validate_record_case_mapping(duplicate_mapping)
    with pytest.raises(ValueError):
        v12.build_candidate_packets(candidate, duplicate_mapping, v12.generate_episode_ids())
    malformed = copy.deepcopy(candidate)
    malformed["cases"][0]["evidence"] = None
    with pytest.raises(ValueError):
        v12.build_candidate_packets(malformed, valid_mapping, v12.generate_episode_ids())
    missing_episode = v12.generate_episode_ids()
    missing_episode.pop(next(iter(missing_episode)))
    with pytest.raises(ValueError):
        v12.build_candidate_packets(candidate, valid_mapping, missing_episode)

    with pytest.raises(ValueError):
        v12.build_candidate_docker_argv("registry/python@sha256:" + "a" * 64, ["python"], "radar-candidate-test", (Path("C:/abs"), "/"))
    assert v12.validate_sandbox_argv([])
    assert v12.validate_sandbox_argv(["--network=none", "--network=none"])

    valid_config = {
        "HostConfig": {
            "NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
            "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges"],
            "Memory": 512 * 1024 * 1024, "MemorySwap": 512 * 1024 * 1024,
            "PidsLimit": 128, "NanoCpus": 1_000_000_000, "CpuQuota": 100_000,
            "PidMode": None, "UTSMode": None, "UsernsMode": None, "IpcMode": "private", "Devices": [],
        },
        "Config": {"User": "65532"}, "Mounts": [],
    }
    for key, value in [("NetworkMode", "host"), ("ReadonlyRootfs", False), ("Privileged", True), ("CapDrop", []), ("Memory", 1), ("MemorySwap", 1), ("PidsLimit", 1), ("NanoCpus", 0), ("PidMode", "host"), ("Devices", ["device"])]:
        variant = copy.deepcopy(valid_config)
        variant["HostConfig"][key] = value
        if key == "NanoCpus":
            variant["HostConfig"]["CpuQuota"] = 0
        assert v12.verify_actual_container_config(variant)
    for user in ("root", ""):
        variant = copy.deepcopy(valid_config)
        variant["Config"]["User"] = user
        assert v12.verify_actual_container_config(variant)
    assert v12.verify_actual_container_config({**valid_config, "Mounts": {}})

    protocol = v12.ExternalCandidateProtocol(["candidate"], working_directory=tmp_path)
    assert protocol._container_name() is None
    monkeypatch.setattr(v12.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")))
    packets = [v12.CandidatePacket(f"e{index}", {}, tuple(sorted(v12.CAPABILITIES))) for index in range(25)]
    assert protocol.run(packets)["error"] == "CANDIDATE_ISOLATION_NOT_PROVEN"
    with v12.secure_temp_workspace() as workspace:
        assert Path(workspace).is_dir()


def test_v07_validation_and_container_failure_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _v07_manifest(tmp_path)
    case = manifest["cases"][0]
    cleanup_fn = v07._cleanup_container
    assert v07._relative_path(tmp_path, "", "path")[1]
    assert v07._relative_path(tmp_path, "C:/outside", "path")[1]
    assert v07._argv([], "cmd")
    assert v07._argv(["python", "--volume"], "cmd")

    bad_variants: list[dict[str, Any]] = []
    for key, value in [("case_id", None), ("corpus_kind", "unknown"), ("platform", None), ("candidate_view", "../escape"), ("candidate_view_digest", ZERO_DIGEST), ("control", None), ("candidate", None), ("capability_recipes", {}), ("prepared_artifacts", [])]:
        variant = copy.deepcopy(case)
        variant[key] = value
        bad_variants.append(variant)
    bad_platform = copy.deepcopy(case)
    bad_platform["platform"].update({"os": "windows", "architecture": "arm64", "container_image": "python:latest"})
    bad_variants.append(bad_platform)
    bad_side = copy.deepcopy(case)
    bad_side["control"].update({"workspace": "missing", "source_digest": "bad", "revision": "x", "command": [], "environment": {1: 2}})
    bad_side["candidate"] = copy.deepcopy(bad_side["control"])
    bad_variants.append(bad_side)
    bad_recipes = copy.deepcopy(case)
    bad_recipes["capability_recipes"] = {capability: None for capability in v07.COMMON_CAPABILITIES}
    bad_variants.append(bad_recipes)
    bad_artifacts = copy.deepcopy(case)
    bad_artifacts["prepared_artifacts"] = [None, {"path": "../escape", "digest": "bad"}]
    bad_variants.append(bad_artifacts)
    assert all(v07._validate_case(variant, tmp_path, 0) for variant in bad_variants)

    for mutation in [
        {"schema_version": "bad"},
        {"evaluation_policy": {}},
        {"capabilities": []},
        {"cases": "bad"},
        {"cases": [1]},
        {"manifest_status": "DRAFT"},
        {"gold": "forbidden"},
    ]:
        variant = copy.deepcopy(manifest)
        variant.update(mutation)
        assert v07.validate_manifest(variant, root=tmp_path)
    duplicate = copy.deepcopy(manifest)
    duplicate["cases"].append(copy.deepcopy(case))
    duplicate["cases"][1]["case_id"] = "CASE-1"
    assert v07.validate_manifest(duplicate, root=tmp_path)
    assert v07.validate_request({"schema_version": v07.PROTOCOL_VERSION, "request_id": "", "episode_id": "", "capability": "bad", "gold": "x"})

    executor = v07.HermeticExecutor(manifest, root=tmp_path)
    monkeypatch.setattr(v07.shutil, "which", lambda _name: "docker")
    monkeypatch.setattr(v07, "_cleanup_container", lambda *_args: {"cleanup_verified": True})
    for capture, expected in [
        (BoundedCapture(0, 0, ZERO_DIGEST, False, True, "timeout"), "TIMEOUT"),
        (BoundedCapture(0, 0, ZERO_DIGEST, True, False, "limit"), "OUTPUT_LIMIT_EXCEEDED"),
        (BoundedCapture(0, 0, ZERO_DIGEST, False, False, "", b"", "cleanup"), "PROCESS_CLEANUP_FAILED"),
    ]:
        monkeypatch.setattr(v07, "run_bounded", lambda *_args, value=capture, **_kwargs: value)
        assert executor._run_side(case, "control", ["python"])["error"] == expected
    monkeypatch.setattr(v07, "run_bounded", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("spawn")))
    assert executor._run_side(case, "control", ["python"])["error"] == "OSError"
    completed = BoundedCapture(0, 1, ZERO_DIGEST, False, False, None)
    monkeypatch.setattr(v07, "run_bounded", lambda *_args, **_kwargs: completed)
    assert executor._run_side(case, "control", ["python"])["status"] == "COMPLETED"

    monkeypatch.setattr(v07, "run_bounded", lambda *_args, **_kwargs: BoundedCapture(1, 0, ZERO_DIGEST, False, False, None))
    cleanup_result = cleanup_fn("docker", "name")
    assert cleanup_result["cleanup_verified"] is False
    monkeypatch.setattr(v07, "run_bounded", lambda *_args, **_kwargs: BoundedCapture(0, 0, ZERO_DIGEST, False, False, None, payload=b"name\n"))
    assert cleanup_fn("docker", "name")["present_after_cleanup"] is True

    passing_metrics = {
        name: {"value": 1.0}
        for name in (
            "action_owner_precision", "candidate_induced_precision", "correct_resolution_or_abstention",
            "safety_abstention_recall", "premature_owner_accusations", "useful_experiment_rate",
            "median_experiments_to_resolution", "naive_resolution", "advantage_over_naive",
            "advantage_over_no_experiment",
        )
    }
    passing_metrics["premature_owner_accusations"]["value"] = 0
    passing_metrics["median_experiments_to_resolution"]["value"] = 1
    passing_metrics["naive_resolution"]["value"] = 0
    passing_metrics["advantage_over_naive"]["value"] = 1
    gates = v07.v07_gates(passing_metrics, {"status": "READY"}, {"digest_match": True})
    assert gates["decision"] == "CONTINUE_TO_PRODUCT"
    none_metrics = {name: {"value": None} for name in passing_metrics}
    assert v07.v07_gates(none_metrics, {"status": "READY"}, {"digest_match": False})["decision"] == "KILL_RADAR_PRODUCT_THESIS"


def test_historical_recipe_and_preparation_failure_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_runtime = ROOT / historical.RUNTIME_RECIPES_RELATIVE
    source_catalog = ROOT / "corpus/v1.0.1/decisive-v1.1/artifact-catalog.json"
    runtime_path = tmp_path / historical.RUNTIME_RECIPES_RELATIVE
    catalog_path = tmp_path / "corpus/v1.0.1/decisive-v1.1/artifact-catalog.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    document = json.loads(source_runtime.read_text(encoding="utf-8"))
    catalog_path.write_bytes(source_catalog.read_bytes())
    for recipe in document["recipes"]:
        relative = Path(str(recipe["reproducer"]))
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())

    def write_variant(value: dict[str, Any]) -> dict[str, Any]:
        runtime_path.write_text(json.dumps(value), encoding="utf-8")
        return historical.validate_runtime_recipes(tmp_path)

    for key, value in [
        ("schema_version", "bad"),
        ("suite_id", "bad"),
        ("network_policy", {}),
        ("build", {}),
        ("recipes", []),
        ("recipes", [None] * 5),
    ]:
        variant = copy.deepcopy(document)
        variant[key] = value
        assert write_variant(variant)["valid"] is False
    recipe_mutations = [
        ("case_id", "unknown"),
        ("recipe_id", "../bad"),
        ("platform", None),
        ("artifacts", []),
        ("reproducer", "../escape"),
        ("filesystem", {}),
        ("preparation", [{"side": "candidate", "command": [], "writes": ["undeclared"]}]),
        ("control", {}),
        ("candidate", {}),
        ("expected", {}),
    ]
    for key, value in recipe_mutations:
        variant = copy.deepcopy(document)
        variant["recipes"][0][key] = value
        assert write_variant(variant)["valid"] is False
    duplicate_case = copy.deepcopy(document)
    duplicate_case["recipes"][1]["case_id"] = duplicate_case["recipes"][0]["case_id"]
    duplicate_case["recipes"][1]["recipe_id"] = duplicate_case["recipes"][0]["recipe_id"]
    assert write_variant(duplicate_case)["valid"] is False

    errors: list[str] = []
    historical._validate_side(
        {
            "case_id": "case",
            "artifacts": ["bundle"],
            "control": {
                "packages": [
                    {"name": "pkg", "version": "1", "wheel": "demo.whl"},
                    {"name": "pkg", "version": "1", "wheel": "demo.whl"},
                ],
                "environment": {"BAD-KEY": "line\n"},
                "command": ["bash", "$(bad)"],
                "expected_exit": -1,
            },
        },
        "control",
        {"bundle": {"demo.whl"}},
        errors,
    )
    assert errors

    staging = tmp_path / "staging"
    destination = tmp_path / "destination"
    staging.mkdir()
    destination.mkdir()
    (staging / "output.txt").write_text("output", encoding="utf-8")
    assert historical._copy_declared_outputs(staging, destination, ["wrong.txt"])[1] == "PREPARATION_OUTPUT_INVENTORY_MISMATCH"
    assert historical._copy_declared_outputs(staging, destination, ["output.txt"])[0] is True
    (staging / "directory").mkdir()
    assert historical._copy_declared_outputs(staging, destination, ["output.txt", "directory"])[1] == "PREPARATION_OUTPUT_INVALID"
    (staging / "directory").rmdir()
    for index in range(historical.MAX_PREPARATION_OUTPUT_FILES + 1):
        (staging / f"extra-{index}.txt").write_text("x", encoding="utf-8")
    assert historical._copy_declared_outputs(staging, destination, [path.name for path in staging.iterdir()])[1] == "PREPARATION_OUTPUT_TOO_MANY_FILES"

    monkeypatch.setattr(historical, "run_bounded", lambda *_args, **_kwargs: BoundedCapture(0, 0, ZERO_DIGEST, True, False, ""))
    assert historical._run_docker(["docker"], timeout=1)["error_type"] == "OUTPUT_LIMIT_EXCEEDED"
    monkeypatch.setattr(historical, "run_bounded", lambda *_args, **_kwargs: BoundedCapture(0, 0, ZERO_DIGEST, False, True, ""))
    assert historical._run_docker(["docker"], timeout=1)["error_type"] == "TIMEOUT"

    sequence = iter([
        {"returncode": 0, "_output": b"", "timed_out": True, "cleanup_error": None},
        {"returncode": 0, "_output": b"", "timed_out": True, "cleanup_error": None},
    ])
    monkeypatch.setattr(historical, "_run_docker", lambda *_args, **_kwargs: next(sequence))
    assert historical._remove_container("docker", "name")["cleanup_verified"] is False
    sequence = iter([
        {"returncode": 0, "_output": b"", "timed_out": False, "cleanup_error": "failed"},
        {"returncode": 0, "_output": b"", "timed_out": False, "cleanup_error": "failed"},
    ])
    monkeypatch.setattr(historical, "_run_docker", lambda *_args, **_kwargs: next(sequence))
    assert historical._remove_volume("docker", "volume")["cleanup_verified"] is False
    sequence = iter([
        {"returncode": 0, "_output": b"", "timed_out": False, "cleanup_error": None},
        {"returncode": 0, "_output": b"image:tag\n", "timed_out": False, "cleanup_error": None},
    ])
    monkeypatch.setattr(historical, "_run_docker", lambda *_args, **_kwargs: next(sequence))
    assert historical._remove_image("docker", "image")["cleanup_verified"] is False

    monkeypatch.setattr(historical, "validate_runtime_recipes", lambda *_args: {"valid": False, "errors": ["bad"]})
    assert historical.reconstruct_historical_cases(tmp_path)["blockers"] == ["HISTORICAL_BUILD_UNREPRODUCIBLE"]
    monkeypatch.setattr(historical, "validate_runtime_recipes", lambda *_args: {"valid": True, "errors": []})
    monkeypatch.setattr(historical, "verify_artifacts", lambda *_args, **_kwargs: {"status": "BLOCKED", "errors": ["missing"]})
    assert historical.reconstruct_historical_cases(tmp_path)["blockers"] == ["ARTIFACT_UNAVAILABLE"]
    monkeypatch.setattr(historical, "verify_artifacts", lambda *_args, **_kwargs: {"status": "READY", "errors": []})
    monkeypatch.setattr(historical.shutil, "which", lambda _name: None)
    assert historical.reconstruct_historical_cases(tmp_path)["blockers"] == ["RUNTIME_UNAVAILABLE"]


def test_release_audit_and_legacy_failure_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    suite = release.load_suite(ROOT)
    source_entry = copy.deepcopy(suite["historical_cases"][0])
    source_manifest = ROOT / release.SUITE_RELATIVE.parent / source_entry["manifest"]
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    entry = {"case_id": source_entry["case_id"], "manifest": "manifest.json"}
    manifest_path = tmp_path / "manifest.json"

    def audit(value: dict[str, Any]) -> dict[str, Any]:
        manifest_path.write_text(json.dumps(value), encoding="utf-8")
        return release._audit_historical_case(
            tmp_path,
            entry,
            tmp_path,
            ROOT / "artifacts/external/decisive-v1.1",
        )

    assert audit(manifest)["valid"] is True
    assert release._audit_historical_case(tmp_path, {"case_id": "x", "manifest": "missing.json"}, tmp_path)["valid"] is False
    assert release._audit_historical_case(tmp_path, {"case_id": "x", "manifest": "../escape"}, tmp_path)["valid"] is False
    for section, mutation in [
        ("case_id", "wrong"),
        ("status", "DRAFT"),
        ("container", {"network": "host", "architecture": "arm64"}),
        ("execution", {}),
        ("runtime_recipe", None),
    ]:
        variant = copy.deepcopy(manifest)
        if section == "case_id":
            variant[section] = mutation
        else:
            variant[section] = mutation
        result = audit(variant)
        if section == "runtime_recipe":
            assert result["valid"] is True
            assert result["status"] == "BLOCKED"
        else:
            assert result["valid"] is False
    variant = copy.deepcopy(manifest)
    variant["execution"] = {"candidate_gold_mounted": True, "candidate_historical_discussion_mounted": True, "candidate_received_control_output": True, "fresh_rerun_1": {}, "fresh_rerun_2": {}}
    assert audit(variant)["valid"] is False

    bundle = manifest.get("artifact_bundle", {})
    assert release._artifact_status({"artifact_bundle": bundle}, artifact_root=None)["available"] is False
    artifact_root = tmp_path / "external"
    artifact_root.mkdir()
    assert release._artifact_status({"artifact_bundle": bundle}, artifact_root=artifact_root)["available"] is False
    bad_bundle = copy.deepcopy(bundle)
    bad_bundle["bundle_id"] = "bundle"
    bad_bundle["files"] = {}
    assert release._artifact_status({"artifact_bundle": bad_bundle}, artifact_root=artifact_root)["available"] is False
    bad_bundle["files"] = {"missing.whl": ZERO_DIGEST}
    (artifact_root / "bundle").mkdir()
    assert release._artifact_status({"artifact_bundle": bad_bundle}, artifact_root=artifact_root)["available"] is False
    (artifact_root / "bundle/missing.whl").write_bytes(b"wrong")
    assert release._artifact_status({"artifact_bundle": bad_bundle}, artifact_root=artifact_root)["available"] is False

    opaque = tmp_path / "opaque"
    opaque.mkdir()
    (opaque / "secret.txt").write_text("historical gold", encoding="utf-8")
    (opaque / "binary.bin").write_bytes(b"\xff\xfe")
    (opaque / "large.txt").write_text("x" * (release.MAX_RUNTIME_FILE_BYTES + 1), encoding="utf-8")
    opacity = release._audit_opacity(tmp_path, [opaque])
    assert opacity["valid"] is False
    assert release._audit_opacity(tmp_path, [opaque / "binary.bin"])["valid"] is True

    monkeypatch.setattr(release, "load_suite", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")))
    assert release.validate_decisive_suite(tmp_path)["valid"] is False
    monkeypatch.setattr(release, "load_suite", lambda *_args, **_kwargs: suite)
    monkeypatch.setattr(release, "validate_runtime_recipes", lambda *_args, **_kwargs: {"valid": False, "errors": ["runtime bad"]})
    invalid = release.validate_decisive_suite(ROOT)
    assert invalid["valid"] is False
    monkeypatch.setattr(release, "validate_runtime_recipes", lambda *_args, **_kwargs: {"valid": True, "errors": [], "recipe_digest": ZERO_DIGEST, "recipe_count": 5})
    monkeypatch.setattr(release, "load_runtime_recipes", lambda *_args, **_kwargs: {"recipes": []})
    assert release.validate_decisive_suite(ROOT)["valid"] is False


def test_v12_executor_boundary_and_cleanup_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    image = "registry/python@sha256:" + "a" * 64
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    bundle_root = tmp_path / "artifacts" / "bundle"
    bundle_root.mkdir(parents=True)
    runtime: dict[str, Any] = {
        "platform": {"container_image": image},
        "artifacts": ["bundle"],
        "control": {"workspace": "workspace", "command": ["python", "-c", "pass"], "environment": {}, "packages": []},
        "candidate": {"workspace": "workspace", "command": ["python", "-c", "pass"], "environment": {}, "packages": []},
    }
    executor = executor_module.V12ExperimentExecutor.__new__(executor_module.V12ExperimentExecutor)
    executor.root = tmp_path.resolve()
    executor.episode_to_case = {"episode": "case"}
    executor.artifact_root = (tmp_path / "artifacts").resolve()
    executor.recipes = {"case": runtime}
    executor.safety = {}
    executor.artifact_status = {"status": "READY"}

    assert executor._workspace({"control": {}}, "control") is None
    fallback = {"reproducer": "workspace/reproducer.py", "control": {"environment": {}}}
    assert executor._workspace(fallback, "control") is not None
    assert executor._workspace({"control": {"workspace": "../bad"}}, "control") is None
    assert executor._docker_argv(runtime, "control", ["python"], input_dir) is not None
    assert executor._docker_argv(runtime, "control", ["python"], "not-a-path") is None
    assert executor._docker_argv({**runtime, "platform": {"container_image": "latest"}}, "control", ["python"], input_dir) is None
    assert executor._docker_argv({**runtime, "control": {**runtime["control"], "environment": []}}, "control", ["python"], input_dir) is None
    assert executor._docker_argv({**runtime, "artifacts": ["../escape"]}, "control", ["python"], input_dir) is None
    no_artifact_root = executor_module.V12ExperimentExecutor.__new__(executor_module.V12ExperimentExecutor)
    no_artifact_root.root = tmp_path.resolve()
    no_artifact_root.artifact_root = None
    no_artifact_root.episode_to_case = {}
    no_artifact_root.recipes = {}
    no_artifact_root.safety = {}
    assert no_artifact_root._docker_argv(runtime, "control", ["python"], input_dir) is None
    assert executor._docker_argv(runtime, "control", ["python"], "bundle", input_volume=True, preparation=True, site_volume="radar-v12-site-" + "a" * 16)
    bad_env = copy.deepcopy(runtime)
    bad_env["control"]["environment"] = {"KEY": 1}
    assert executor._docker_argv(bad_env, "control", ["python"], input_dir) is None
    assert executor._command_for({}, "control", {}) is None
    bad_command = copy.deepcopy(runtime)
    bad_command["control"]["command"] = ["bash", "-c", "pass"]
    assert executor._command_for(bad_command, "control", {"capability": "rerun", "parameters": {}}) is None
    assert executor._installing_command(runtime, "candidate", ["python", "-c", "pass"], {"capability": "change_dependency_version", "parameters": {"target_component": "x", "version": "1"}}) == ["python", "-c", "pass"]

    capture = BoundedCapture(0, 1, ZERO_DIGEST, False, False, "ok")
    monkeypatch.setattr(executor_module.shutil, "which", lambda _name: "docker")
    monkeypatch.setattr(executor_module, "run_bounded", lambda *_args, **_kwargs: capture)
    monkeypatch.setattr(executor, "_cleanup_container", lambda _name: {"cleanup_verified": False})
    result = executor._run_side({**runtime, "artifacts": []}, "control", ["python", "-c", "pass"], input_dir, {"capability": "rerun"})
    assert result.cleanup_error == "CONTAINER_CLEANUP_UNVERIFIED"
    monkeypatch.setattr(executor, "_cleanup_container", lambda _name: {"cleanup_verified": True})
    monkeypatch.setattr(executor, "_cleanup_volume", lambda _name: {"cleanup_verified": False})
    assert executor._copy_volume_to_staging(runtime, "volume", tmp_path).cleanup_error is None
    monkeypatch.setattr(executor, "_cleanup_container", lambda _name: {"cleanup_verified": False})
    assert executor._copy_volume_to_staging(runtime, "volume", tmp_path).cleanup_error == "CONTAINER_CLEANUP_UNVERIFIED"
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    assert executor._audit_preparation_output(audit_dir, ["missing"])[1] == "PREPARATION_OUTPUT_INVENTORY_MISMATCH"
    noisy = tmp_path / "noisy"
    noisy.mkdir()
    for index in range(executor_module.MAX_PREPARATION_OUTPUT_FILES + 1):
        (noisy / f"file-{index}.txt").write_text("x", encoding="utf-8")
    assert executor._audit_preparation_output(noisy, [path.name for path in noisy.iterdir()])[1] == "PREPARATION_OUTPUT_TOO_MANY_FILES"
    assert executor._evaluator_receipt({"capability": "rerun"}, BoundedCapture(0, 0, ZERO_DIGEST, False, True, ""), capture)["fresh"] is False

    executor.artifact_root = None
    assert executor("episode", {"capability": "rerun", "parameters": {}})["observation"]["status"] == "ARTIFACT_UNAVAILABLE"
    executor.artifact_root = tmp_path / "artifacts"
    executor.artifact_status = {"status": "BLOCKED"}
    assert executor("episode", {"capability": "rerun", "parameters": {}})["observation"]["status"] == "ARTIFACT_UNAVAILABLE"
    executor.artifact_status = {"status": "READY"}
    runtime_no_prep = copy.deepcopy(runtime)
    runtime_no_prep["artifacts"] = []
    executor.recipes = {"case": runtime_no_prep}
    monkeypatch.setattr(executor, "_run_side", lambda *_args, **_kwargs: capture)
    assert executor("episode", {"capability": "rerun", "parameters": {}})["status"] == "COMPLETED"
    control_missing = copy.deepcopy(runtime_no_prep)
    control_missing["control"].pop("command")
    executor.recipes = {"case": control_missing}
    assert executor("episode", {"capability": "rerun", "parameters": {}})["observation"]["status"] == "CONTROL_COMMAND_NOT_DECLARED_BY_RECIPE"


def test_v12_reference_protocol_and_package_audit_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    candidate_audit = v12.candidate_bundle_audit(ROOT)
    reference = json.loads((ROOT / v12.V12_SOLVABILITY_RELATIVE).read_text(encoding="utf-8"))
    assert not v12._validate_solvability_reference(ROOT, {"digest": candidate_audit["digest"]}, reference)
    missing_scored_component = copy.deepcopy(reference)
    episode = next(
        item["episode_id"]
        for item in missing_scored_component["historical_review"]
        if item["role"] == "A01_OR_OTHER"
    )
    next(item for item in missing_scored_component["raw_predictions"] if item["episode_id"] == episode)["causal_component"] = None
    assert v12._validate_solvability_reference(
        ROOT, {"digest": candidate_audit["digest"]}, missing_scored_component
    )
    unknown_role = copy.deepcopy(reference)
    unknown_role["historical_review"][0]["role"] = "UNKNOWN_ROLE"
    assert v12._validate_solvability_reference(
        ROOT, {"digest": candidate_audit["digest"]}, unknown_role
    )
    exact_component_mutations = {
        "A01_OR_OTHER": "numpy",
        "A03_AMBIGUOUS": "scipy",
        "A04_OR_OTHER": "numpy",
        "A05_OR_OTHER": "numpy",
    }
    for role, wrong_component in exact_component_mutations.items():
        variant = copy.deepcopy(reference)
        episode = next(item["episode_id"] for item in variant["historical_review"] if item["role"] == role)
        prediction = next(item for item in variant["raw_predictions"] if item["episode_id"] == episode)
        prediction["causal_component"] = wrong_component
        assert v12._validate_solvability_reference(ROOT, {"digest": candidate_audit["digest"]}, variant)
    evaluator_visible = copy.deepcopy(reference)
    evaluator_visible["sandbox_receipt"]["evaluator_mount_count"] = 1
    evaluator_visible["evaluator_available_during_run"] = True
    assert v12._validate_solvability_reference(
        ROOT, {"digest": candidate_audit["digest"]}, evaluator_visible
    )
    mutations: list[dict[str, Any]] = [
        {"review_type": "wrong"},
        {"raw_predictions": []},
        {"receipts": []},
        {"evaluator_available_during_run": True},
        {"candidate_bundle_digest": "bad"},
        {"historical_review": []},
        {"metadata_only": {}},
    ]
    for mutation in mutations:
        variant = copy.deepcopy(reference)
        variant.update(mutation)
        assert v12._validate_solvability_reference(ROOT, {"digest": candidate_audit["digest"]}, variant)
    invalid_predictions = copy.deepcopy(reference)
    invalid_predictions["raw_predictions"] = [
        None,
        {"episode_id": "same", "disposition": "bad", "semantic_intent": "bad", "causal_component": 1, "candidate_induced": "bad", "evidence_digest": "bad", "gold": True},
        {"episode_id": "same", "disposition": "ATTRIBUTED", "semantic_intent": "known", "causal_component": None, "candidate_induced": True, "evidence_digest": ZERO_DIGEST},
        *copy.deepcopy(reference["raw_predictions"])[3:],
    ]
    invalid_predictions["receipts"] = [None, {"status": "BAD", "receipt_digest": "bad", "fresh": False, "experiment_count": 99}, *copy.deepcopy(reference["receipts"])[2:]]
    invalid_predictions["historical_review"] = [None, {"episode_id": "unknown", "role": "bad"}, *copy.deepcopy(reference["historical_review"])[2:]]
    assert v12._validate_solvability_reference(ROOT, {"digest": candidate_audit["digest"]}, invalid_predictions)

    absent = v12.ExternalCandidateProtocol(["candidate"], working_directory=tmp_path / "missing")
    assert absent.run([])["error"] == "CANDIDATE_WORKSPACE_ABSENT"
    legacy = v12.ExternalCandidateProtocol(["candidate"], working_directory=tmp_path)
    assert legacy.run([])["error"] == "CANDIDATE_ISOLATION_NOT_PROVEN"
    protocol = v12.ExternalCandidateProtocol("registry/python@sha256:" + "a" * 64, ["python"], working_directory=tmp_path)
    packets = [v12.CandidatePacket(f"episode-{index}", {}, tuple(sorted(v12.CAPABILITIES))) for index in range(25)]
    assert protocol.run(packets[:-1])["error"] == "CANDIDATE_CASE_SET_INVALID"
    monkeypatch.setattr(v12.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")))
    assert protocol.run(packets)["error"] == "CANDIDATE_PROCESS_UNAVAILABLE"
    monkeypatch.setattr(protocol, "_actual_container_config", lambda: [])

    assert v12.separation_audit(ROOT)["valid"] is True
    assert v12.source_package_mirror_audit(ROOT)["status"] == "PASS"
    assert v12.compare_exact_reference({"metrics": {"x": 1}}, None)["status"] == "NO_REFERENCE"
    assert v12.compare_exact_reference({"metrics": {"x": 1}}, {"metrics": {"x": 2}})["status"] == "DRIFT"
    assert v12.validate_file_manifest(tmp_path, {"files": [{"path": "missing", "bytes": 0, "sha256": ZERO_DIGEST}]} )["valid"] is False


def test_artifact_fetch_loop_and_verify_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wheel = _wheel_bytes()
    digest = "sha256:" + hashlib.sha256(wheel).hexdigest()
    bundle = artifacts.ArtifactBundle(
        "bundle", ("case",), (), "wheel", "x86_64", "3.11.0", len(wheel),
        artifacts._bundle_digest({"demo-1.0-py3-none-any.whl": (digest, len(wheel))}),
        "RECONSTRUCT_ONLY", (), (artifacts.ArtifactFile("demo-1.0-py3-none-any.whl", digest, len(wheel)),),
    )
    catalog = {"catalog_policy": "test"}
    monkeypatch.setattr(artifacts, "_load_bundles", lambda *_args: (catalog, (bundle,)))
    monkeypatch.setattr(artifacts, "_source_url", lambda *_args: "https://files.pythonhosted.org/packages/d/demo-1.0-py3-none-any.whl")
    monkeypatch.setattr(artifacts, "_download", lambda _url, destination, _expected: destination.write_bytes(wheel))
    monkeypatch.setattr(artifacts, "verify_artifacts", lambda *_args, **_kwargs: {"status": "READY", "catalog_digest": ZERO_DIGEST, "bundles": [], "errors": []})
    fetched = artifacts.fetch_artifacts(tmp_path, "decisive-v1.2", tmp_path / "external")
    assert fetched["status"] == "READY"
    assert fetched["network_used"] is True
    assert (tmp_path / "external/provenance.json").is_file()

    unclear = artifacts.ArtifactBundle(bundle.artifact_id, bundle.case_ids, bundle.incidents, bundle.format, bundle.architecture, bundle.python, bundle.total_bytes, bundle.bundle_digest, "UNCLEAR_DO_NOT_PUBLISH", bundle.provenance, bundle.files)
    monkeypatch.setattr(artifacts, "_load_bundles", lambda *_args: (catalog, (unclear,)))
    monkeypatch.setattr(artifacts, "verify_artifacts", lambda *_args, **_kwargs: {"status": "BLOCKED", "catalog_digest": ZERO_DIGEST, "bundles": [], "errors": ["missing"]})
    blocked = artifacts.fetch_artifacts(tmp_path, "decisive-v1.2", tmp_path / "unclear")
    assert blocked["status"] == "BLOCKED"
    assert any("unresolved" in error for error in blocked["errors"])

    broken = tmp_path / "broken"
    broken.mkdir()
    monkeypatch.setattr(artifacts, "_load_bundles", lambda *_args: (catalog, (bundle,)))
    monkeypatch.setattr(artifacts, "_download", lambda *_args: (_ for _ in ()).throw(artifacts.ArtifactContractError("download failed")))
    monkeypatch.setattr(artifacts, "verify_artifacts", lambda *_args, **_kwargs: {"status": "BLOCKED", "catalog_digest": ZERO_DIGEST, "bundles": [], "errors": []})
    failed = artifacts.fetch_artifacts(tmp_path, "decisive-v1.2", broken)
    assert failed["status"] == "BLOCKED"
    assert "download failed" in failed["errors"]


def test_v12_result_contract_and_release_execution_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    valid = _completed_result()
    for mutation in [
        {"schema_version": "bad"},
        {"suite_id": "bad"},
        {"release_version": "bad"},
        {"status": "DRIFT"},
        {"candidate_gold_visible": True},
        {"candidate_repository_visible": True},
        {"network_used": True},
        {"blockers": "bad"},
        {"runs": {}},
        {"episode_count": 1},
        {"protocol": None},
        {"metrics": None},
        {"predictions": {}},
        {"experiment_receipts": {}},
        {"candidate_bundle_digest": "bad", "evaluator_bundle_digest": "bad", "runtime_digest": "bad", "artifact_catalog_digest": "bad", "mapping_digest": "bad"},
        {"baseline_digests": {"x": "bad"}},
        {"platform_contract": {}},
        {"isolation_verification": {}},
        {"source_provenance": {}},
        {"cleanup_status": {}},
    ]:
        variant = copy.deepcopy(valid)
        variant.update(mutation)
        assert v12.validate_v12_result_document(variant)
    malformed_run = copy.deepcopy(valid)
    malformed_run["runs"][v12.ALL_CASE_IDS[0]]["prediction"] = _prediction(disposition="bad")
    assert v12.validate_v12_result_document(malformed_run)
    malformed_prediction = copy.deepcopy(valid)
    malformed_prediction["predictions"][v12.ALL_CASE_IDS[0]] = _prediction(disposition="bad")
    assert v12.validate_v12_result_document(malformed_prediction)
    malformed_receipt = copy.deepcopy(valid)
    malformed_receipt["experiment_receipts"][v12.ALL_CASE_IDS[0]] = None
    assert v12.validate_v12_result_document(malformed_receipt)
    missing_required = {"status": "BLOCKED"}
    assert v12.validate_v12_result_document(missing_required)

    audit = {
        "valid": True,
        "historical": [{"case_id": case_id, "block_reason": None} for case_id in release.HISTORICAL_IDS],
        "safety": {"count": 20},
    }
    runtime = SimpleNamespace(available=True, supported=True, engine_os="linux", engine_architecture="x86_64", reason=None)
    harness_result = {"status": "COMPLETED", "cases": [], "lanes": {}, "metrics": {}}
    monkeypatch.setattr(release, "validate_decisive_suite", lambda *_args, **_kwargs: audit)
    monkeypatch.setattr(release, "inspect_docker_runtime", lambda: runtime)
    monkeypatch.setattr(release, "reconstruct_historical_cases", lambda *_args, **_kwargs: {"status": "READY"})
    monkeypatch.setattr(release, "CanonicalHarness", lambda *_args, **_kwargs: SimpleNamespace(run=lambda _runtime: harness_result))
    def fake_build_result(*_args: object, **kwargs: Any) -> dict[str, Any]:
        raw = kwargs.get("raw", {})
        return {
            "canonical_reproduction": {"status": "MATCHED_NEGATIVE_CONCLUSION"},
            "status": str(raw.get("status", "BLOCKED")),
        }

    monkeypatch.setattr(release, "build_result", fake_build_result)
    monkeypatch.setattr(release, "validate_result_document", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(release, "file_digest", lambda _path: ZERO_DIGEST)
    executed = release.evaluate_decisive_suite(ROOT, artifact_root=tmp_path)
    assert executed["status"] == "COMPLETED"

    monkeypatch.setattr(release, "reconstruct_historical_cases", lambda *_args, **_kwargs: {"status": "BLOCKED", "blockers": ["ARTIFACT_UNAVAILABLE"]})
    blocked_runtime = release.evaluate_decisive_suite(ROOT, artifact_root=tmp_path)
    assert blocked_runtime["status"] == "BLOCKED"
    monkeypatch.setattr(release, "reconstruct_historical_cases", lambda *_args, **_kwargs: {"status": "READY"})
    monkeypatch.setattr(release, "CanonicalHarness", lambda *_args, **_kwargs: SimpleNamespace(run=lambda _runtime: {"status": "BLOCKED", "blockers": ["HARNESS"]}))
    blocked_harness = release.evaluate_decisive_suite(ROOT, artifact_root=tmp_path)
    assert blocked_harness["status"] == "BLOCKED"


def test_v12_result_required_fields_and_artifact_contract_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    valid = _completed_result()
    for key in (
        "candidate_bundle_digest", "evaluator_bundle_digest", "runtime_digest",
        "artifact_catalog_digest", "baseline_digests", "protocol_version",
        "executor_capability_version", "platform_contract", "isolation_verification",
        "experiment_receipts", "predictions", "source_provenance", "cleanup_status",
        "decision", "scientific_classification",
    ):
        variant = copy.deepcopy(valid)
        variant.pop(key)
        assert v12.validate_v12_result_document(variant)

    candidate_catalog = json.loads(
        (ROOT / artifacts.V12_CATALOG_RELATIVE).read_text(encoding="utf-8")
    )
    recipes = json.loads(
        (ROOT / artifacts.V12_SUITE_RELATIVE.parent / "runtime-recipes.json").read_text(encoding="utf-8")
    )

    def load_variant(catalog: dict[str, Any], recipe_doc: dict[str, Any] | None = None) -> None:
        def fake_read(path: Path) -> dict[str, Any]:
            if path.name == "artifact-catalog.json":
                return copy.deepcopy(catalog)
            return copy.deepcopy(recipe_doc if recipe_doc is not None else recipes)

        monkeypatch.setattr(artifacts, "_read_json", fake_read)
        with pytest.raises(artifacts.ArtifactContractError):
            artifacts._load_v12_bundles(tmp_path)

    wrong_identity = copy.deepcopy(candidate_catalog)
    wrong_identity["schema_version"] = "bad"
    load_variant(wrong_identity)
    wrong_bundles = copy.deepcopy(candidate_catalog)
    wrong_bundles["bundles"] = []
    load_variant(wrong_bundles)
    invalid_bundle = copy.deepcopy(candidate_catalog)
    invalid_bundle["bundles"][0]["artifact_id"] = "../escape"
    load_variant(invalid_bundle)
    duplicate_bundle = copy.deepcopy(candidate_catalog)
    duplicate_bundle["bundles"][1]["artifact_id"] = duplicate_bundle["bundles"][0]["artifact_id"]
    load_variant(duplicate_bundle)
    invalid_recipes = copy.deepcopy(recipes)
    invalid_recipes["recipes"] = []
    load_variant(candidate_catalog, invalid_recipes)
    invalid_recipe = copy.deepcopy(recipes)
    invalid_recipe["recipes"][0]["case_id"] = None
    load_variant(candidate_catalog, invalid_recipe)
    invalid_artifacts = copy.deepcopy(recipes)
    invalid_artifacts["recipes"][0]["artifacts"] = []
    load_variant(candidate_catalog, invalid_artifacts)
    unknown_artifact = copy.deepcopy(recipes)
    unknown_artifact["recipes"][0]["artifacts"] = ["missing-bundle"]
    load_variant(candidate_catalog, unknown_artifact)
    invalid_inventory = copy.deepcopy(candidate_catalog)
    invalid_inventory["bundles"][0]["files"] = "bad"
    load_variant(invalid_inventory)
    invalid_file = copy.deepcopy(candidate_catalog)
    invalid_file["bundles"][0]["files"][0]["name"] = "../bad.whl"
    load_variant(invalid_file)
    invalid_metadata = copy.deepcopy(candidate_catalog)
    invalid_metadata["bundles"][0]["total_bytes"] = -1
    load_variant(invalid_metadata)
    invalid_status = copy.deepcopy(candidate_catalog)
    invalid_status["bundles"][0]["redistribution_status"] = "UNKNOWN"
    load_variant(invalid_status)
    missing_case = copy.deepcopy(candidate_catalog)
    missing_case["bundles"][0]["case_ids"] = []
    load_variant(missing_case)

    payload = _wheel_bytes()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    bundle = artifacts.ArtifactBundle(
        "demo", ("case",), (), "wheel", "x86_64", "3.11", len(payload),
        artifacts._bundle_digest({"demo-1.0-py3-none-any.whl": (digest, len(payload))}),
        "RECONSTRUCT_ONLY", (), (artifacts.ArtifactFile("demo-1.0-py3-none-any.whl", digest, len(payload)),),
    )
    root = tmp_path / "external" / "demo"
    root.mkdir(parents=True)
    wheel = root / "demo-1.0-py3-none-any.whl"
    wheel.write_bytes(payload)
    assert artifacts._verify_bundle(bundle, tmp_path / "external")["status"] == "READY"
    wheel.write_bytes(b"bad")
    assert artifacts._verify_bundle(bundle, tmp_path / "external")["status"] == "BLOCKED"
    wheel.unlink()
    (root / "link.whl").symlink_to(tmp_path / "missing.whl")
    assert artifacts._verify_bundle(bundle, tmp_path / "external")["status"] == "BLOCKED"


def test_bounded_process_success_limit_and_argument_guards() -> None:
    with pytest.raises(ValueError):
        process_module.run_bounded([], timeout=1, max_output_bytes=10)
    with pytest.raises(ValueError):
        process_module.run_bounded(["python"], timeout=0, max_output_bytes=10)
    with pytest.raises(ValueError):
        process_module.run_bounded(["python"], timeout=1, max_output_bytes=0)
    success = process_module.run_bounded(
        ["python", "-c", "print('ok')"], timeout=5, max_output_bytes=1024, input_data=b"ignored"
    )
    assert success.returncode == 0
    assert success.timed_out is False
    overflow = process_module.run_bounded(
        ["python", "-c", "print('x' * 4096)"], timeout=5, max_output_bytes=32
    )
    assert overflow.output_limit_exceeded is True


def test_external_protocol_docker_inspection_and_cleanup_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    protocol = v12.ExternalCandidateProtocol(
        "registry/python@sha256:" + "a" * 64,
        ["python"],
        working_directory=tmp_path,
    )
    calls = 0

    def run_cleanup(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(argv, 0, b"container", b"")
        if calls == 2:
            return subprocess.CompletedProcess(argv, 1, b"", b"remove failed")
        return subprocess.CompletedProcess(argv, 1, b"", b"no such object")

    monkeypatch.setattr(v12.subprocess, "run", run_cleanup)
    assert protocol._cleanup_container() is False
    calls = 0

    def run_removed(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        if calls < 3:
            return subprocess.CompletedProcess(argv, 0, b"container", b"")
        return subprocess.CompletedProcess(argv, 1, b"", b"no such container")

    monkeypatch.setattr(v12.subprocess, "run", run_removed)
    assert protocol._cleanup_container() is True
    monkeypatch.setattr(v12.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("docker")))
    assert protocol._cleanup_container() is False

    monkeypatch.setattr(
        v12.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["docker"], 0, b"[]", b""),
    )
    assert protocol._actual_container_config()
    monkeypatch.setattr(
        v12.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["docker"], 0, b"not-json", b""),
    )
    assert protocol._actual_container_config()[0].startswith("candidate container inspect failed")
    monkeypatch.setattr(
        v12.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 1, b"", b"no such object"),
    )
    protocol._candidate_process = SimpleNamespace(returncode=17, poll=lambda: 17)  # type: ignore[assignment]
    assert protocol._actual_container_config()[0].startswith(
        "candidate container process exited before inspection"
    )
    protocol._candidate_process = None


def test_external_protocol_stream_absence_and_cleanup_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packets = [
        v12.CandidatePacket(f"episode-{index}", {}, tuple(sorted(v12.CAPABILITIES)))
        for index in range(len(v12.ALL_CASE_IDS))
    ]

    class Stdin:
        def write(self, value: bytes) -> int:
            return len(value)

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    class Process:
        stdin = Stdin()
        stdout = None
        stderr = None
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, **_kwargs: object) -> int:
            self.returncode = 0
            return 0

        def kill(self) -> None:
            self.returncode = -9

    process = Process()
    protocol = v12.ExternalCandidateProtocol(
        "registry/python@sha256:" + "a" * 64,
        ["python"],
        working_directory=tmp_path,
    )
    monkeypatch.setattr(v12.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(protocol, "_actual_container_config", lambda: [])
    monkeypatch.setattr(protocol, "_cleanup_container", lambda: True)
    result = protocol.run(packets)
    assert result["status"] == "BLOCKED"
    assert "CANDIDATE_OUTPUT_LIMIT" in result["errors"]

    process = Process()
    monkeypatch.setattr(v12.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(protocol, "_cleanup_container", lambda: (_ for _ in ()).throw(OSError("cleanup")))
    result = protocol.run(packets)
    assert "CANDIDATE_CONTAINER_CLEANUP_FAILED" in result["errors"]

    process = Process()
    process.returncode = -1
    monkeypatch.setattr(v12.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(protocol, "_cleanup_container", lambda: False)
    result = protocol.run(packets)
    assert "CANDIDATE_CONTAINER_CLEANUP_FAILED" in result["errors"]

    timeout_protocol = v12.ExternalCandidateProtocol(
        "registry/python@sha256:" + "a" * 64,
        ["python"],
        working_directory=tmp_path,
        timeout_seconds=0,
    )
    process = Process()
    monkeypatch.setattr(v12.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(timeout_protocol, "_actual_container_config", lambda: [])
    monkeypatch.setattr(timeout_protocol, "_cleanup_container", lambda: True)
    assert "CANDIDATE_TIMEOUT" in timeout_protocol.run(packets)["errors"]

    class BrokenStdin(Stdin):
        def write(self, value: bytes) -> int:
            raise BrokenPipeError("closed")

    process = Process()
    process.stdin = BrokenStdin()
    process.returncode = None
    monkeypatch.setattr(v12.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(protocol, "_cleanup_container", lambda: True)
    assert "CANDIDATE_PROCESS_IO_ERROR" in protocol.run(packets)["errors"]


def test_external_protocol_partial_frame_and_timeout_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packets = [
        v12.CandidatePacket(f"episode-{index}", {}, tuple(sorted(v12.CAPABILITIES)))
        for index in range(len(v12.ALL_CASE_IDS))
    ]

    class Stream:
        def __init__(self, descriptor: int) -> None:
            self.descriptor = descriptor

        def fileno(self) -> int:
            return self.descriptor

    class Stdin:
        def write(self, value: bytes) -> int:
            return len(value)

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    class Process:
        def __init__(self, stdout: Stream, stderr: Stream) -> None:
            self.stdin = Stdin()
            self.stdout = stdout
            self.stderr = stderr
            self.returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, **_kwargs: object) -> int:
            self.returncode = 0
            return 0

        def kill(self) -> None:
            self.returncode = -9

    output_read, output_write = os.pipe()
    error_read, error_write = os.pipe()
    os.write(output_write, b"partial-frame")
    os.close(output_write)
    os.close(error_write)
    process = Process(Stream(output_read), Stream(error_read))
    protocol = v12.ExternalCandidateProtocol(
        "registry/python@sha256:" + "a" * 64,
        ["python"],
        working_directory=tmp_path,
    )
    monkeypatch.setattr(v12.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(protocol, "_actual_container_config", lambda: [])
    monkeypatch.setattr(protocol, "_cleanup_container", lambda: True)
    result = protocol.run(packets)
    os.close(output_read)
    os.close(error_read)
    assert "CANDIDATE_PARTIAL_JSONL_FRAME" in result["errors"]


def test_small_protocol_and_bundle_error_edges(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        v12.ExternalCandidateProtocol([], working_directory=tmp_path)
    legacy = v12.ExternalCandidateProtocol(["candidate"], working_directory=tmp_path)
    assert legacy._actual_container_config()[0] == "candidate container name is unavailable"
    candidate_path = tmp_path / v12.V12_CANDIDATE_BUNDLE_RELATIVE
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text("[]", encoding="utf-8")
    assert v12.candidate_bundle_audit(tmp_path)["valid"] is False
