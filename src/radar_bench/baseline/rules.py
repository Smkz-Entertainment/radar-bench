"""Named, fail-closed deterministic rule predicates."""

from __future__ import annotations

from typing import Any


def apply_rules(features: dict[str, Any]) -> tuple[str, str, str, list[str], list[str]]:
    fired: list[str] = []
    considered: list[str] = []
    text = features["text"]
    if any(
        marker in text
        for marker in ("404", "dns", "tls", "remote fixture", "external service")
    ):
        fired.append("external-service-failure")
        return (
            "not_candidate_induced",
            "external_service_or_data",
            "medium",
            fired,
            ["candidate-ab"],
        )
    if any(
        marker in text
        for marker in (
            "artifact missing",
            "not found on index",
            "wheel upload",
            "uninstallable",
        )
    ):
        fired.append("artifact-unavailable")
        return (
            "not_candidate_induced",
            "packaging_or_artifact",
            "medium",
            fired,
            ["dependency-resolution-check"],
        )
    if features["control_status"] in {"fail", "error", "timeout"} and features[
        "candidate_status"
    ] in {"fail", "error", "timeout"}:
        considered.append("baseline-already-broken")
        if features.get("fingerprint"):
            fired.append("control-and-candidate-fail")
            return (
                "not_candidate_induced",
                "unknown",
                "low",
                fired,
                ["clean-control-rerun"],
            )
        return (
            "inconclusive",
            "unknown",
            "inconclusive",
            fired,
            ["repeat-control-candidate"],
        )
    if "worker crash" in text or "xdist" in text or "flaky" in text:
        fired.append("one-off-worker-or-flaky-signal")
        return (
            "inconclusive",
            "flaky_or_nondeterministic",
            "inconclusive",
            fired,
            ["repeat-runs"],
        )
    if features["control_status"] == "pass" and features["candidate_status"] in {
        "fail",
        "error",
        "timeout",
    }:
        fired.append("control-passes-candidate-fails")
        return (
            "confirmed_regression",
            "upstream_runtime_or_library",
            "medium",
            fired,
            ["candidate-ab"],
        )
    considered.extend(
        [
            "control-passes-candidate-fails",
            "baseline-already-broken",
            "external-service-failure",
        ]
    )
    return (
        "inconclusive",
        "unknown",
        "inconclusive",
        fired,
        ["repeat-runs", "candidate-ab"],
    )
