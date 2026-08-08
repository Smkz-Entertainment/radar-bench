"""Deterministic v0.3 lane, layered on the frozen v0.2 rules."""

from __future__ import annotations

from typing import Any

from radar_bench.baseline.engine import predict_v02
from radar_bench.baseline.features import extract_features
from radar_bench.models.prediction import make_prediction


def predict_v03(packet: dict[str, Any]) -> dict[str, Any]:
    """Emit ontology fields without consulting post-cutoff or gold material."""

    base = predict_v02(packet)
    features = extract_features(packet)
    signals = list(features.get("confounder_signals", []))
    evidence_class = "CONFOUNDED" if base["verdict"] == "confounded_change" else (
        "CANDIDATE_SPECIFIC" if base["verdict"] == "confirmed_regression" else "OBSERVED"
    )
    component = packet.get("upstream_change", {}).get("project")
    change = packet.get("upstream_change", {}).get("candidate", {}).get("version")
    first_bad = base.get("first_bad")
    first_bad_value = first_bad.get("value") if isinstance(first_bad, dict) else first_bad
    values = dict(base)
    values.update(
        {
            "schema_version": "0.3",
            "trigger_component": component,
            "trigger_change": str(change) if change is not None else None,
            "manifestation_project": packet.get("downstream_subject", {}).get("project"),
            "manifestation_layer": base.get("responsible_layer"),
            "root_cause_component": component if not signals else None,
            "root_cause_mechanism": None,
            "action_owner_repository": base.get("owner_repository") if not signals else None,
            "first_bad_version_or_revision": first_bad_value,
            "confounders": signals,
            "evidence_class": evidence_class,
            "evidence_classes": [evidence_class],
            "provider_version": "0.3.0",
        }
    )
    return make_prediction(**values)
