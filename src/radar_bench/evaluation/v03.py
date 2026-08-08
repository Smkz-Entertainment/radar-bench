"""v0.3 field-level attribution, safety, calibration, and difficulty metrics."""

from __future__ import annotations

from typing import Any

from radar_bench.evaluation.statistics import safety_confidence
from radar_bench.evaluation.v02 import (
    _first_bad_key,
    _metric,
    is_abstention,
    is_gold_abstention,
    score_v02,
)
from radar_bench.models.ontology import field_match


def _valid(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [value for value in values if value.get("_valid", True)]


def _label(labels: dict[str, dict[str, Any]], prediction: dict[str, Any]) -> dict[str, Any]:
    case_id = prediction.get("case_id")
    value = labels.get(case_id, {}) if isinstance(case_id, str) else {}
    return value if isinstance(value, dict) else {}


def _field_metric(
    predictions: list[dict[str, Any]], labels: dict[str, dict[str, Any]], field: str
) -> dict[str, Any]:
    answered = [
        prediction
        for prediction in _valid(predictions)
        if not is_abstention(prediction) and _label(labels, prediction)
    ]
    correct = [
        prediction
        for prediction in answered
        if field_match(prediction, _label(labels, prediction), field)
    ]
    expected = [
        label
        for label in labels.values()
        if not is_gold_abstention(label) and label.get(field) is not None
    ]
    return {
        "precision": _metric(len(correct), len(answered)),
        "recall": _metric(len(correct), len(expected)),
        "field": field,
    }


def _first_bad_metric(
    predictions: list[dict[str, Any]], labels: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    expected = {
        case_id: label
        for case_id, label in labels.items()
        if _first_bad_key(label.get("first_bad_version_or_revision", label.get("first_bad")))
        is not None
    }
    correct = [
        prediction
        for prediction in _valid(predictions)
        if prediction.get("case_id") in expected
        and _first_bad_key(prediction.get("first_bad_version_or_revision", prediction.get("first_bad")))
        == _first_bad_key(expected[prediction["case_id"]].get("first_bad_version_or_revision", expected[prediction["case_id"]].get("first_bad")))
    ]
    return _metric(len(correct), len(expected))


def _difficulty_metrics(
    predictions: list[dict[str, Any]], labels: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    tiers: dict[str, dict[str, Any]] = {}
    for tier in ("D1", "D2", "D3", "D4", "D5"):
        subset = {
            case_id: label for case_id, label in labels.items() if label.get("difficulty") == tier
        }
        subset_predictions = [
            prediction for prediction in predictions if prediction.get("case_id") in subset
        ]
        tiers[tier] = {
            "cases": len(subset),
            "candidate_induction": _field_metric(
                subset_predictions, subset, "candidate_induced"
            ),
            "action_owner": _field_metric(
                subset_predictions, subset, "action_owner_repository"
            ),
        }
    return tiers


def calculate_metrics_v03(
    predictions: list[dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    *,
    corpus_kind: str = "attribution_gold",
) -> dict[str, Any]:
    valid = _valid(predictions)
    base = score_v02(valid, labels)["metrics"]
    safety_labels = {
        key: value
        for key, value in labels.items()
        if value.get("corpus_kind") == "safety_abstention"
        or value.get("should_abstain") is True
    }
    safety_predictions = [
        prediction for prediction in valid if prediction.get("case_id") in safety_labels
    ]
    false_high_upstream = [
        prediction
        for prediction in safety_predictions
        if float(prediction.get("confidence_score", 0.0)) >= 0.9
        and prediction.get("responsible_layer") == "upstream_runtime_or_library"
    ]
    field_metrics = {
        "candidate_induction": {
            "precision": base["attribution_precision"],
            "recall": base["attribution_recall"],
        },
        "causal_component": _field_metric(valid, labels, "root_cause_component"),
        "action_owner": _field_metric(
            valid,
            {
                case_id: label
                for case_id, label in labels.items()
                if label.get("action_owner_scored", True)
            },
            "action_owner_repository",
        ),
        "first_bad": _first_bad_metric(valid, labels),
    }
    return {
        "counts": {
            **base["counts"],
            "safety_labels": len(safety_labels),
            "safety_predictions": len(safety_predictions),
            "corpus_kind": corpus_kind,
        },
        "candidate_induction": field_metrics["candidate_induction"],
        "causal_component": field_metrics["causal_component"],
        "action_owner": field_metrics["action_owner"],
        "first_bad": field_metrics["first_bad"],
        "abstention": {
            "precision": base["abstention_precision"],
            "recall": base["abstention_recall"],
        },
        "false_high_confidence_upstream": safety_confidence(
            len(false_high_upstream), len(safety_predictions)
        ),
        "unsupported_confident_claims": base["unsupported_confident_claims"],
        "calibration": base["calibration"],
        "difficulty": _difficulty_metrics(valid, labels),
        "experiments": {
            "requested": base["experiments_requested"],
            "useful": base["experiments_useful"],
            "useful_ratio": {
                "value": (
                    base["experiments_useful"]["value"] / base["experiments_requested"]["value"]
                    if base["experiments_requested"]["value"]
                    else None
                )
            },
        },
        "usage": base["usage"],
    }


def score_v03(
    predictions: list[dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    *,
    corpus_kind: str = "attribution_gold",
) -> dict[str, Any]:
    return {
        "protocol_version": "0.3",
        "exploratory": True,
        "metrics": calculate_metrics_v03(predictions, labels, corpus_kind=corpus_kind),
    }
