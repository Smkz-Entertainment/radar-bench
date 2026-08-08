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
    environments = packet.get("environments", {})
    control_delta = environments.get("control", {})
    candidate_delta = environments.get("candidate", {})
    confounder_signals: list[str] = []
    if (
        control_delta.get("dependency_snapshot_digest")
        and candidate_delta.get("dependency_snapshot_digest")
        and control_delta["dependency_snapshot_digest"]
        != candidate_delta["dependency_snapshot_digest"]
    ):
        confounder_signals.append("dependency-snapshot-changed")
    if (
        control_delta.get("runtime")
        and candidate_delta.get("runtime")
        and control_delta["runtime"] != candidate_delta["runtime"]
    ):
        confounder_signals.append("runtime-changed")
    if control_delta.get("variables", {}) != candidate_delta.get("variables", {}):
        confounder_signals.append("environment-variables-changed")
    if any(
        marker in lower
        for marker in (
            "transitive dependency",
            "resolver",
            "different dependency",
            "pip installed",
            "environment changed",
            "python 3.16",
        )
    ):
        confounder_signals.append("text-reports-confounder")
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
        "confounder_signals": confounder_signals,
    }
