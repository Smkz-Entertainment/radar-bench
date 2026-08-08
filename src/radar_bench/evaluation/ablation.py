"""Provider-lane comparison with explicit incremental-value accounting."""

from __future__ import annotations

from typing import Any

from radar_bench.evaluation.v02 import score_v02


def _value(report: dict[str, Any], name: str) -> float | None:
    value = report.get("metrics", {}).get(name, {}).get("value")
    return float(value) if isinstance(value, (int, float)) else None


def compare_lanes(
    lanes: dict[str, list[dict[str, Any]]],
    labels: dict[str, dict[str, Any]],
    accounting: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    reports = {name: score_v02(values, labels) for name, values in lanes.items()}
    accounting = accounting or {}
    for name, records in accounting.items():
        reports.setdefault(name, {})["accounting"] = {
            "records": len(records),
            "tokens": sum(int(value.get("tokens") or 0) for value in records),
            "cost": sum(float(value.get("cost") or 0.0) for value in records),
            "wall_clock_seconds": sum(
                float(value.get("wall_clock_seconds") or 0.0) for value in records
            ),
            "experiments_requested": sum(
                int(value.get("experiments_requested") or 0) for value in records
            ),
            "experiments_useful": sum(
                int(value.get("experiments_useful") or 0) for value in records
            ),
        }
    deterministic = reports.get("deterministic", {})
    codex = reports.get("codex", {})
    lifts = {}
    for metric in (
        "attribution_precision",
        "attribution_recall",
        "abstention_precision",
        "abstention_recall",
    ):
        baseline = _value(deterministic, metric)
        candidate = _value(codex, metric)
        if baseline is not None and candidate is not None:
            lifts[metric] = candidate - baseline
    deterministic_false = (
        _value(deterministic, "false_high_confidence_upstream_accusations") or 0.0
    )
    codex_false = _value(codex, "false_high_confidence_upstream_accusations") or 0.0
    best_lift = max(lifts.values(), default=None)
    return {
        "protocol_version": "0.2",
        "lanes": reports,
        "codex_incremental_value": {
            "metric_lifts": lifts,
            "best_lift": best_lift,
            "added_false_high_confidence_upstream_accusations": codex_false
            - deterministic_false,
            "qualifies": best_lift is not None
            and best_lift >= 0.01
            and codex_false <= deterministic_false,
            "rule": "Codex needs >=0.01 lift on a scored quality metric and may not add false high-confidence upstream accusations.",
        },
    }


def v03_lane_plan(
    input_manifest_digest: str,
    *,
    deterministic_scored_cases: int = 0,
    local_model_available: bool = False,
    codex_available: bool = False,
) -> dict[str, Any]:
    """Describe v0.3 lanes without turning unavailable credentials into passes."""

    def lane(name: str, available: bool, scored: int) -> dict[str, Any]:
        if not available:
            status = "blocked_external"
            error = "lane requires an unavailable local model or credential"
        elif scored == 0:
            status = "not_run"
            error = "no independently admitted labeled cases"
        else:
            status = "completed"
            error = None
        return {
            "schema_version": "0.3",
            "run_id": f"ABL-V03-{name.upper().replace('_', '-')}",
            "lane": name,
            "status": status,
            "input_manifest_digest": input_manifest_digest,
            "network_policy": "denied",
            "scored_cases": scored,
            "metrics": {},
            "experiments_requested": 0,
            "experiments_useful": 0,
            "unsupported_confident_claims": 0,
            "error": error,
        }

    lanes = {
        "deterministic": lane("deterministic", True, deterministic_scored_cases),
        "local_model": lane("local_model", local_model_available, deterministic_scored_cases),
        "codex": lane("codex", codex_available, deterministic_scored_cases),
    }
    return {
        "protocol_version": "0.3",
        "exploratory": True,
        "lanes": lanes,
        "qualification": {
            "status": "blocked_until_same_hidden_cases_are_scored",
            "rule": "permanent role requires measurable difficult-case or efficiency lift with no safety worsening",
        },
    }
