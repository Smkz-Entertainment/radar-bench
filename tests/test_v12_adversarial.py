from __future__ import annotations

import json
from pathlib import Path

import pytest

from radar_bench.artifacts import verify_artifacts
from radar_bench.v1_2 import (
    ALL_CASE_IDS,
    SAFETY_IDS,
    baseline_freeze_audit,
    build_candidate_docker_argv,
    candidate_bundle_audit,
    metadata_shape_classifier_audit,
    score_v12,
    validate_prediction,
    validate_protocol_message,
    verify_actual_container_config,
)

ROOT = Path(__file__).resolve().parents[1]


def test_candidate_shape_is_uniform_and_case_type_tokens_are_absent() -> None:
    document = json.loads((ROOT / "candidate/decisive-v1.2/candidate-bundle.json").read_text())
    assert candidate_bundle_audit(ROOT)["valid"] is True
    assert metadata_shape_classifier_audit(document)["status"] == "PASS"
    shapes = {tuple(sorted(item["evidence"])) for item in document["cases"]}
    assert len(shapes) == 1


def test_terminal_protocol_rejects_evaluator_fields_and_missing_fields() -> None:
    prediction = {
        "causal_component": None,
        "candidate_induced": False,
        "semantic_intent": "not-applicable",
        "action_owner": None,
        "disposition": "ABSTAINED",
        "evidence_ids": [],
    }
    assert validate_prediction(prediction) == []
    forged = {"schema_version": "1.2-jsonl", "message": "final_prediction", "episode_id": "ep-test", "prediction": prediction, "fresh": True}
    assert validate_protocol_message(forged) == ["final_prediction: unexpected fields"]
    assert validate_protocol_message({"message": "final_prediction", "episode_id": "ep-test", "prediction": prediction})


def test_docker_sandbox_is_strict_and_inspect_is_fail_closed(tmp_path: Path) -> None:
    image = "registry.example/candidate@sha256:" + "a" * 64
    argv = build_candidate_docker_argv(image, ["radar-agent", "--protocol", "1.2-jsonl"], "radar-candidate-test")
    assert "--network=none" in argv
    assert "--read-only" in argv
    with pytest.raises(ValueError):
        build_candidate_docker_argv("registry.example/candidate:latest", ["agent"], "radar-candidate-test")
    assert verify_actual_container_config({"HostConfig": {}, "Config": {}})


def test_v12_score_uses_terminal_fields_and_unsupported_owner_claims() -> None:
    document = json.loads((ROOT / "evaluator/decisive-v1.2/evaluator-bundle.json").read_text())
    labels = document["labels"]["cases"]
    runs = {}
    for case_id in ALL_CASE_IDS:
        label = labels[case_id]
        runs[case_id] = {"prediction": {"causal_component": label["causal_component"], "candidate_induced": label["candidate_induced"], "semantic_intent": label["semantic_intent"], "action_owner": label["action_owner_repository"], "disposition": label["disposition"], "evidence_ids": []}}
    runs[SAFETY_IDS[0]]["prediction"]["action_owner"] = "unsupported-owner"
    metrics = score_v12(labels, runs)["metrics"]
    assert metrics["cross_repository_resolution"]["value"] == 1.0
    assert metrics["semantic_ambiguity_handling"]["value"] == 1.0
    assert metrics["false_owner_accusation_rate"]["numerator"] == 1


def test_historical_gold_and_frozen_git_source_are_observable() -> None:
    assert baseline_freeze_audit(ROOT)["status"] == "PASS"
    artifacts = verify_artifacts(ROOT, "decisive-v1.2", ROOT / "artifacts" / "external" / "decisive-v1.2")
    assert artifacts["status"] == "BLOCKED"
    assert artifacts["network_used"] is False
