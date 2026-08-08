"""Metric calculations with explicit denominators."""

from __future__ import annotations

from collections import Counter
from typing import Any


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _label_for(
    labels: dict[str, dict[str, Any]], item: dict[str, Any]
) -> dict[str, Any]:
    case_id = item.get("case_id")
    return labels.get(case_id, {}) if isinstance(case_id, str) else {}


def calculate_metrics(
    predictions: list[dict[str, Any]], labels: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    valid = [item for item in predictions if item.get("_valid", True)]
    confirmed = [
        item
        for item in valid
        if item.get("verdict") == "confirmed_regression"
        and item.get("candidate_induced") is True
    ]
    gold_confirmed = [
        item
        for case_id, item in labels.items()
        if item.get("candidate_induced") is True
    ]
    true_confirmed = [
        item
        for item in confirmed
        if _label_for(labels, item).get("candidate_induced") is True
    ]
    high = [
        item
        for item in valid
        if item.get("confidence") in {"high", "confirmed"}
        and item.get("responsible_layer") != "unknown"
    ]
    high_true = [
        item
        for item in high
        if _label_for(labels, item).get("responsible_layer")
        == item.get("responsible_layer")
    ]
    negatives = [
        item
        for case_id, item in labels.items()
        if item.get("responsible_layer")
        in {
            "flaky_or_nondeterministic",
            "ci_or_infrastructure",
            "external_service_or_data",
            "unknown",
        }
        or item.get("should_abstain")
    ]
    abstained = [
        item
        for item in predictions
        if item.get("verdict") == "inconclusive"
        or item.get("candidate_induced") is None
    ]
    neg_ids = {case_id for case_id, _ in labels.items() if _ in negatives}
    abstain_neg = [item for item in abstained if item.get("case_id") in neg_ids]
    upstream = [
        item
        for item in valid
        if item.get("responsible_layer") == "upstream_runtime_or_library"
        and item.get("confidence") in {"high", "confirmed"}
    ]
    false_upstream = [
        item
        for item in upstream
        if _label_for(labels, item).get("responsible_layer")
        != "upstream_runtime_or_library"
    ]
    invalid = [item for item in predictions if item.get("_valid") is False]
    cited = [item for item in predictions if item.get("evidence_ids")]
    valid_cited = [item for item in cited if item.get("_valid", False)]
    temporal = [
        item for item in cited if item.get("_temporal_valid", item.get("_valid", False))
    ]
    layer_counts = Counter(
        (
            _label_for(labels, item).get("responsible_layer", "unknown"),
            item.get("responsible_layer", "unknown"),
        )
        for item in valid
    )
    return {
        "counts": {
            "predictions": len(predictions),
            "valid": len(valid),
            "invalid": len(invalid),
            "confirmed_predictions": len(confirmed),
            "gold_confirmed": len(gold_confirmed),
            "high_layer_predictions": len(high),
            "negative_cases": len(negatives),
        },
        "candidate_induced_precision": {
            "value": _ratio(len(true_confirmed), len(confirmed)),
            "numerator": len(true_confirmed),
            "denominator": len(confirmed),
        },
        "candidate_induced_recall": {
            "value": _ratio(len(true_confirmed), len(gold_confirmed)),
            "numerator": len(true_confirmed),
            "denominator": len(gold_confirmed),
        },
        "high_confidence_layer_precision": {
            "value": _ratio(len(high_true), len(high)),
            "numerator": len(high_true),
            "denominator": len(high),
        },
        "false_upstream_accusation_rate": {
            "value": _ratio(len(false_upstream), len(upstream)),
            "numerator": len(false_upstream),
            "denominator": len(upstream),
        },
        "negative_case_abstention_recall": {
            "value": _ratio(len(abstain_neg), len(negatives)),
            "numerator": len(abstain_neg),
            "denominator": len(negatives),
        },
        "invalid_prediction_rate": {
            "value": _ratio(len(invalid), len(predictions)),
            "numerator": len(invalid),
            "denominator": len(predictions),
        },
        "evidence_citation_validity": {
            "value": _ratio(len(valid_cited), len(cited)),
            "numerator": len(valid_cited),
            "denominator": len(cited),
        },
        "temporal_citation_validity": {
            "value": _ratio(len(temporal), len(cited)),
            "numerator": len(temporal),
            "denominator": len(cited),
        },
        "confusion": {
            f"{left}->{right}": count for (left, right), count in layer_counts.items()
        },
    }
