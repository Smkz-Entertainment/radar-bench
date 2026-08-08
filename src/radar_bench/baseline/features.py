"""Extract inspectable features from an inference packet."""

from __future__ import annotations

from typing import Any


def extract_features(packet: dict[str, Any]) -> dict[str, Any]:
    outcomes = packet.get("outcomes", {})
    control = outcomes.get("control", {})
    candidate = outcomes.get("candidate", {})
    texts = (
        " ".join(str(value) for value in packet.get("failure", {}).values())
        + " "
        + str(packet.get("environments", {}))
    )
    lower = texts.lower()
    return {
        "control_status": control.get("status", "unknown"),
        "candidate_status": candidate.get("status", "unknown"),
        "control_attempts": control.get("attempts", 0),
        "candidate_attempts": candidate.get("attempts", 0),
        "fingerprint": packet.get("failure", {}).get("fingerprint"),
        "text": lower,
        "evidence_ids": packet.get("evidence_ids", []),
        "kind": packet.get("upstream_change", {}).get("kind"),
        "project": packet.get("upstream_change", {}).get("project"),
        "candidate_version": packet.get("upstream_change", {})
        .get("candidate", {})
        .get("version"),
    }
