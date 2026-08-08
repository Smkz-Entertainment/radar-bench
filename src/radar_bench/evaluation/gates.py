"""Machine-readable future product gates; no zero-denominator pass-through."""

from __future__ import annotations

from typing import Any

GATES = {
    "candidate_induced_regression_precision": (0.95, "gte"),
    "high_confidence_layer_precision": (0.95, "gte"),
    "false_upstream_accusation_rate": (0.01, "lt"),
    "negative_case_abstention_recall": (0.95, "gte"),
    "first_bad_localization_accuracy": (0.90, "gte"),
    "clean_reproducer_success": (0.95, "gte"),
    "known_cause_retrieval": (0.95, "gte"),
    "temporal_citation_validity": (1.0, "eq"),
}


def evaluate_gates(report: dict[str, Any]) -> dict[str, Any]:
    metrics = report.get("metrics", report)
    result: dict[str, Any] = {}
    for name, (threshold, comparator) in GATES.items():
        metric = metrics.get(name, {})
        value = metric.get("value") if isinstance(metric, dict) else metric
        if value is None:
            result[name] = {
                "status": "not_evaluable",
                "value": None,
                "threshold": threshold,
            }
        else:
            passed = (
                value >= threshold
                if comparator == "gte"
                else value < threshold
                if comparator == "lt"
                else value == threshold
            )
            result[name] = {
                "status": "pass" if passed else "fail",
                "value": value,
                "threshold": threshold,
            }
    return {
        "exploratory": True,
        "gates": result,
        "recommendation": "Do not treat the seed set as production evidence.",
    }
