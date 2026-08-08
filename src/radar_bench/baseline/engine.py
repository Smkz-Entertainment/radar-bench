"""Deterministic baseline provider over an immutable inference packet."""

from __future__ import annotations

from typing import Any

from radar_bench.baseline.features import extract_features
from radar_bench.baseline.rules import apply_rules
from radar_bench.models.prediction import make_prediction


def predict(packet: dict[str, Any]) -> dict[str, Any]:
    features = extract_features(packet)
    verdict, layer, confidence, fired, considered = apply_rules(features)
    candidate_induced = (
        True
        if verdict == "confirmed_regression"
        else False
        if verdict == "not_candidate_induced"
        else None
    )
    cite = list(features["evidence_ids"][:3])
    recommendation = (
        {
            "kind": "ab",
            "question": "Run the same minimized workload under a controlled candidate/control pair.",
        }
        if verdict == "inconclusive"
        else None
    )
    rationale = (
        "Rules fired: "
        + (", ".join(fired) if fired else "none")
        + ". Rules not satisfied: "
        + ", ".join(considered)
        + ". Evidence is limited to the inference-visible packet; no gold history was consulted."
    )
    return make_prediction(
        case_id=packet["case_id"],
        verdict=verdict,
        candidate_induced=candidate_induced,
        responsible_layer=layer,
        rationale=rationale,
        evidence_ids=cite,
        confidence=confidence,
        provider="deterministic",
        provider_version="0.1.0",
        recommended_next_experiment=recommendation,
    )
