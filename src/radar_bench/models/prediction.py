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
    try:
        validate_json(prediction, "prediction", root)
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
    return errors


def make_prediction(**values: Any) -> dict[str, Any]:
    values.setdefault("schema_version", "0.1")
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
    return values
