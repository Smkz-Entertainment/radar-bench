"""Prediction model helpers and evidence-aware confidence policy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from radar_bench.errors import ValidationError
from radar_bench.schema.loader import validate_json


def validate_prediction(
    prediction: dict[str, Any],
    evidence: dict[str, dict[str, Any]] | None = None,
    *,
    root: Any = None,
) -> list[str]:
    errors: list[str] = []
    schema_kind = (
        "prediction_v02" if prediction.get("schema_version") == "0.2" else "prediction"
    )
    try:
        validate_json(prediction, schema_kind, root)
    except ValidationError as exc:
        return exc.errors
    if evidence is not None:
        for evidence_id in prediction["evidence_ids"]:
            item = evidence.get(evidence_id)
            if item is None:
                errors.append(f"evidence_ids: unknown evidence {evidence_id}")
            elif item.get("available_before_cutoff") is False:
                errors.append(f"evidence_ids: post-cutoff evidence {evidence_id}")
    if prediction["confidence"] in {"confirmed", "high"}:
        if prediction["verdict"] != "confirmed_regression":
            errors.append(
                "high/confirmed confidence requires confirmed_regression verdict"
            )
        if not prediction["evidence_ids"]:
            errors.append("high/confirmed confidence requires evidence citations")
        if (
            prediction["provider"] in {"local_model", "codex"}
            and prediction.get("rationale", "").lower().find("experiment") < 0
        ):
            errors.append(
                "model output cannot upgrade confidence without explicit evidence-rule rationale"
            )
    if schema_kind == "prediction_v02":
        if prediction["verdict"] == "confounded_change":
            if prediction.get("candidate_induced") is not None:
                errors.append("confounded_change must leave candidate_induced null")
            if prediction.get("responsible_layer") == "upstream_runtime_or_library":
                errors.append("confounded_change cannot assign upstream ownership")
        classes = prediction.get("evidence_classes", [])
        if prediction.get("confidence_score", 0.0) >= 0.9 and not any(
            value in {"CAUSALLY_SUPPORTED", "CONFIRMED"} for value in classes
        ):
            errors.append(
                "confidence_score >= 0.9 requires CAUSALLY_SUPPORTED or CONFIRMED evidence"
            )
    return errors


def make_prediction(**values: Any) -> dict[str, Any]:
    schema_version = values.setdefault("schema_version", "0.1")
    values.setdefault("owner_repository", None)
    values.setdefault("owner_project", None)
    values.setdefault("owner_candidates", [])
    values.setdefault("intentionality", "unknown")
    values.setdefault("first_bad", None)
    values.setdefault("recommended_next_experiment", None)
    values.setdefault("cost", None)
    values.setdefault(
        "created_at", datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    if schema_version == "0.2":
        confidence = values.get("confidence", "inconclusive")
        values.setdefault(
            "confidence_score",
            {
                "confirmed": 0.99,
                "high": 0.9,
                "medium": 0.65,
                "low": 0.35,
                "inconclusive": 0.2,
            }.get(confidence, 0.2),
        )
        values.setdefault("evidence_classes", ["OBSERVED"])
        values.setdefault(
            "experiments_requested",
            1 if values.get("recommended_next_experiment") else 0,
        )
        values.setdefault("experiments_useful", 0)
        values.setdefault(
            "usage",
            {
                "input_tokens": None,
                "output_tokens": None,
                "amount": None,
                "currency": None,
                "wall_clock_seconds": None,
            },
        )
    return values
