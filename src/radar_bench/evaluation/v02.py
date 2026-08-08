"""v0.2 attribution, abstention, calibration, and efficiency metrics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return numerator / denominator if denominator else None


def _metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "value": _ratio(numerator, denominator),
        "numerator": numerator,
        "denominator": denominator,
    }


def is_abstention(prediction: dict[str, Any]) -> bool:
    return prediction.get("verdict") in {"inconclusive", "confounded_change"} or (
        prediction.get("candidate_induced") is None
    )


def is_gold_abstention(label: dict[str, Any]) -> bool:
    """Use explicit gold intent, falling back conservatively for v0.1 labels."""

    return bool(
        label.get("should_abstain")
        or label.get("candidate_induced") is None
        or label.get("confidence") == "inconclusive"
    )


def _correct(prediction: dict[str, Any], label: dict[str, Any]) -> bool:
    if is_gold_abstention(label):
        return is_abstention(prediction)
    if is_abstention(prediction):
        return False
    if prediction.get("candidate_induced") != label.get("candidate_induced"):
        return False
    return prediction.get("responsible_layer") == label.get("responsible_layer")


def _label_for(
    labels: dict[str, dict[str, Any]], prediction: dict[str, Any]
) -> dict[str, Any]:
    case_id = prediction.get("case_id")
    return labels.get(case_id, {}) if isinstance(case_id, str) else {}


def _first_bad_key(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None
    for key in ("value", "revision", "version", "exact"):
        if value.get(key) is not None:
            return str(value[key])
    return None


def _calibration(
    predictions: list[dict[str, Any]], labels: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    bins: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for prediction in predictions:
        if not prediction.get("_valid", True):
            continue
        label = _label_for(labels, prediction)
        score = prediction.get("confidence_score")
        if not isinstance(label, dict) or not isinstance(score, (float, int)):
            continue
        numeric = max(0.0, min(1.0, float(score)))
        bins[min(9, int(numeric * 10))].append((numeric, _correct(prediction, label)))
    rendered: list[dict[str, Any]] = []
    total = sum(len(values) for values in bins.values())
    ece = 0.0
    brier = 0.0
    for index in range(10):
        values = bins.get(index, [])
        if not values:
            continue
        mean_confidence = sum(value[0] for value in values) / len(values)
        accuracy = sum(value[1] for value in values) / len(values)
        ece += len(values) / total * abs(mean_confidence - accuracy)
        brier += sum((value[0] - float(value[1])) ** 2 for value in values) / total
        rendered.append(
            {
                "lower": index / 10,
                "upper": (index + 1) / 10,
                "count": len(values),
                "mean_confidence": mean_confidence,
                "accuracy": accuracy,
            }
        )
    return {
        "evaluated_predictions": total,
        "expected_calibration_error": ece if total else None,
        "brier_score": brier if total else None,
        "bins": rendered,
    }


def calculate_metrics_v02(
    predictions: list[dict[str, Any]], labels: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    valid = [item for item in predictions if item.get("_valid", True)]
    answered = [item for item in valid if not is_abstention(item)]
    abstained = [item for item in valid if is_abstention(item)]
    gold_answered = [
        value for value in labels.values() if not is_gold_abstention(value)
    ]
    gold_abstain = [value for value in labels.values() if is_gold_abstention(value)]
    correct = [
        item
        for item in valid
        if _label_for(labels, item) and _correct(item, _label_for(labels, item))
    ]
    correct_answered = [item for item in correct if not is_abstention(item)]
    correct_abstained = [item for item in correct if is_abstention(item)]
    high_confidence = [
        item
        for item in valid
        if isinstance(item.get("confidence_score"), (int, float))
        and item["confidence_score"] >= 0.9
        and not is_abstention(item)
    ]
    high_correct = [
        item
        for item in high_confidence
        if _label_for(labels, item) and _correct(item, _label_for(labels, item))
    ]
    false_upstream = [
        item
        for item in high_confidence
        if item.get("responsible_layer") == "upstream_runtime_or_library"
        and (
            _label_for(labels, item).get("responsible_layer")
            != "upstream_runtime_or_library"
        )
    ]
    unsupported = [
        item
        for item in valid
        if isinstance(item.get("confidence_score"), (int, float))
        and item["confidence_score"] >= 0.9
        and not any(
            value in {"CAUSALLY_SUPPORTED", "CONFIRMED"}
            for value in item.get("evidence_classes", [])
        )
    ]
    first_bad_labels = {
        case_id: value
        for case_id, value in labels.items()
        if _first_bad_key(value.get("first_bad")) is not None
    }
    first_bad_predictions = [
        item
        for item in valid
        if item.get("case_id") in first_bad_labels
        and _first_bad_key(item.get("first_bad")) is not None
        and _first_bad_key(item.get("first_bad"))
        == _first_bad_key(first_bad_labels[item["case_id"]].get("first_bad"))
    ]
    requested = sum(int(item.get("experiments_requested", 0)) for item in valid)
    useful = sum(int(item.get("experiments_useful", 0)) for item in valid)
    usage = {
        "input_tokens": sum(
            int(item.get("usage", {}).get("input_tokens") or 0) for item in valid
        ),
        "output_tokens": sum(
            int(item.get("usage", {}).get("output_tokens") or 0) for item in valid
        ),
        "amount": sum(
            float(item.get("usage", {}).get("amount") or 0.0) for item in valid
        ),
        "wall_clock_seconds": sum(
            float(item.get("usage", {}).get("wall_clock_seconds") or 0.0)
            for item in valid
        ),
    }
    cited = [item for item in valid if item.get("evidence_ids")]
    temporal = [
        item for item in cited if item.get("_temporal_valid", item.get("_valid", False))
    ]
    return {
        "counts": {
            "predictions": len(predictions),
            "valid": len(valid),
            "invalid": len(predictions) - len(valid),
            "answered": len(answered),
            "abstained": len(abstained),
            "gold_answered": len(gold_answered),
            "gold_abstain": len(gold_abstain),
            "high_confidence": len(high_confidence),
        },
        "attribution_precision": _metric(len(correct_answered), len(answered)),
        "attribution_recall": _metric(len(correct_answered), len(gold_answered)),
        "abstention_precision": _metric(len(correct_abstained), len(abstained)),
        "abstention_recall": _metric(len(correct_abstained), len(gold_abstain)),
        "high_confidence_attribution_precision": _metric(
            len(high_correct), len(high_confidence)
        ),
        "false_high_confidence_upstream_accusations": {
            "value": len(false_upstream),
            "numerator": len(false_upstream),
            "denominator": len(high_confidence),
        },
        "unsupported_confident_claims": {
            "value": len(unsupported),
            "numerator": len(unsupported),
            "denominator": len(valid),
        },
        "first_bad_localization_accuracy": _metric(
            len(first_bad_predictions), len(first_bad_labels)
        ),
        "temporal_citation_validity": _metric(len(temporal), len(cited)),
        "experiments_requested": {"value": requested, "count": len(valid)},
        "experiments_useful": {"value": useful, "count": len(valid)},
        "usage": usage,
        "calibration": _calibration(predictions, labels),
    }


def score_v02(
    predictions: list[dict[str, Any]], labels: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    return {
        "protocol_version": "0.2",
        "exploratory": True,
        "metrics": calculate_metrics_v02(predictions, labels),
    }
