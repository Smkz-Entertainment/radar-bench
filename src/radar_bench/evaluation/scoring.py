"""Prediction JSONL loading and deterministic scoring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from radar_bench.evaluation.metrics import calculate_metrics
from radar_bench.evaluation.v02 import score_v02
from radar_bench.models.prediction import validate_prediction


def load_predictions(
    path: Path, evidence_by_case: dict[str, dict[str, dict[str, Any]]] | None = None
) -> list[dict[str, Any]]:
    result = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError("prediction is not an object")
            case_id = value.get("case_id")
            evidence = (
                (evidence_by_case or {}).get(case_id)
                if evidence_by_case is not None and isinstance(case_id, str)
                else None
            )
            errors = validate_prediction(value, evidence)
            valid = not bool(errors)
            value["_line"] = line_number
            value["_valid"] = valid
            value["_validation_errors"] = errors
        except (ValueError, TypeError) as exc:
            result.append(
                {
                    "_valid": False,
                    "_line": line_number,
                    "_error": str(exc),
                    "case_id": "<invalid>",
                }
            )
            continue
        result.append(value)
    return result


def score(
    predictions: list[dict[str, Any]], labels: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    if any(item.get("schema_version") == "0.2" for item in predictions):
        return score_v02(predictions, labels)
    return {
        "protocol_version": "0.1",
        "exploratory": True,
        "metrics": calculate_metrics(predictions, labels),
    }
