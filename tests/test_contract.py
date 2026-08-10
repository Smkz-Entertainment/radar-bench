from __future__ import annotations

import json
from pathlib import Path

import pytest

from radar_bench.artifacts import verify_artifacts
from radar_bench.errors import ValidationError
from radar_bench.historical_runtime import validate_runtime_recipes
from radar_bench.release import evaluate_decisive_suite, validate_decisive_suite
from radar_bench.result_contract import build_result, validate_result_document


ROOT = Path(__file__).resolve().parents[1]


def test_suite_and_runtime_contracts_are_valid() -> None:
    suite = validate_decisive_suite(ROOT)
    assert suite["valid"] is True
    runtime = validate_runtime_recipes(ROOT)
    assert runtime["valid"] is True
    assert runtime["recipe_count"] == 5


def test_missing_external_inputs_are_blocked_and_strict() -> None:
    result = evaluate_decisive_suite(ROOT)
    assert result["status"] == "BLOCKED"
    assert result["cases"]["executed"] == 0
    assert result["cases"]["blocked"] == 25
    validate_result_document(result, ROOT)
    artifacts = verify_artifacts(ROOT, "decisive-v1.1")
    assert artifacts["status"] == "BLOCKED"
    assert artifacts["network_used"] is False


def test_reference_result_is_strict_and_not_runtime_evidence() -> None:
    result = json.loads(
        (ROOT / "reference" / "decisive-v1.1-result.json").read_text(encoding="utf-8")
    )
    validate_result_document(result, ROOT)
    assert result["canonical_reproduction"]["reference_used_as_runtime_evidence"] is False
    assert result["candidate_gold_separation"]["gold_visible_to_candidate"] is False


def test_build_result_can_compare_a_blocked_run_to_reference() -> None:
    reference = json.loads(
        (ROOT / "reference" / "decisive-v1.1-result.json").read_text(encoding="utf-8")
    )
    audit = validate_decisive_suite(ROOT)
    result = build_result(
        ROOT,
        raw={"status": "BLOCKED", "cases": {"executed": 0, "blocked_cases": []}},
        audit=audit,
        platform={"engine_os": "unknown", "engine_architecture": "unknown"},
        reference=reference,
        reference_digest="sha256:" + "0" * 64,
    )
    assert result["canonical_reproduction"]["status"] == "RESULT_MISMATCH"
    validate_result_document(result, ROOT)


def test_strict_result_rejects_unknown_properties() -> None:
    result = json.loads(
        (ROOT / "reference" / "decisive-v1.1-result.json").read_text(encoding="utf-8")
    )
    result["unexpected"] = True
    with pytest.raises(ValidationError):
        validate_result_document(result, ROOT)


@pytest.mark.parametrize(
    "mutation",
    [
        "remove_required",
        "denominator_drift",
        "partial_predictions",
        "extra_metric_field",
    ],
)
def test_adversarial_result_contract_mutations_are_rejected(
    mutation: str,
) -> None:
    result = json.loads(
        (ROOT / "reference" / "decisive-v1.1-result.json").read_text(encoding="utf-8")
    )
    if mutation == "remove_required":
        del result["decision"]
    elif mutation == "denominator_drift":
        result["baselines"]["agentic-v0.5-frozen"]["metrics"]["historical_positive_resolution"]["denominator"] = 4
    elif mutation == "partial_predictions":
        result["case_predictions"]["static-v0.4"] = result["case_predictions"]["static-v0.4"][:-1]
    elif mutation == "extra_metric_field":
        result["baselines"]["static-v0.4"]["metrics"]["historical_positive_resolution"]["extra"] = True
    with pytest.raises(ValidationError):
        validate_result_document(result, ROOT)


def test_case_sequence_drift_is_rejected_after_schema_validation() -> None:
    result = json.loads(
        (ROOT / "reference" / "decisive-v1.1-result.json").read_text(encoding="utf-8")
    )
    predictions = result["case_predictions"]["static-v0.4"]
    predictions[0], predictions[1] = predictions[1], predictions[0]
    with pytest.raises(ValidationError) as raised:
        validate_result_document(result, ROOT)
    assert any("exact canonical case sequence" in error for error in raised.value.errors)
