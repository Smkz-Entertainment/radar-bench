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


def predict_v02(packet: dict[str, Any]) -> dict[str, Any]:
    """Run the v0.2 conservative lane without changing the frozen v0.1 output."""

    prediction = predict(packet)
    features = extract_features(packet)
    signals = features["confounder_signals"]
    if (
        prediction["verdict"] == "confirmed_regression"
        and prediction["candidate_induced"] is True
        and signals
    ):
        prediction.update(
            {
                "verdict": "confounded_change",
                "candidate_induced": None,
                "responsible_layer": (
                    "dependency_resolution"
                    if any(
                        "dependency" in value or "resolver" in value
                        for value in signals
                    )
                    else "multiple_layers"
                ),
                "confidence": "inconclusive",
                "recommended_next_experiment": {
                    "kind": "inspect",
                    "question": "Hold runtime and dependency resolution constant before assigning causal ownership.",
                },
                "rationale": prediction["rationale"]
                + " v0.2 abstention shield: "
                + ", ".join(signals)
                + "; causal ownership is confounded.",
            }
        )
    if prediction["verdict"] in {"confirmed_regression", "not_candidate_induced"}:
        evidence_classes = ["REPRODUCED"]
    elif prediction["verdict"] == "confounded_change":
        evidence_classes = ["REPRODUCED"]
    else:
        evidence_classes = ["OBSERVED"]
    confidence_score = {
        "confirmed": 0.65,
        "high": 0.75,
        "medium": 0.65,
        "low": 0.35,
        "inconclusive": 0.2,
    }[prediction["confidence"]]
    prediction.update(
        {
            "schema_version": "0.2",
            "provider_version": "0.2.0",
            "evidence_classes": evidence_classes,
            "confidence_score": confidence_score,
        }
    )
    return make_prediction(**prediction)
