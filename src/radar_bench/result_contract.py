"""Strict, versioned result contract for the corrected executable suite."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, cast

from radar_bench.errors import ValidationError
from radar_bench.schema.loader import validate_json

LANES = ("static-v0.4", "naive-deterministic", "agentic-v0.5-frozen")
METRICS = (
    "historical_positive_resolution",
    "candidate_induced_correctness",
    "action_owner_correctness",
    "cross_repository_resolution",
    "semantic_ambiguity_handling",
    "safety_abstention_recall",
    "false_owner_accusation_rate",
    "premature_owner_accusations",
    "useful_experiment_rate",
    "median_substantive_experiments",
    "advantage_over_naive_positive_resolution",
)
HISTORICAL_IDS = tuple(f"RADAR-V07-A{i:02d}" for i in range(1, 6))
SAFETY_IDS = tuple(f"RADAR-V07-T{i:02d}" for i in range(1, 21))


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _empty_metric(denominator: int = 0) -> dict[str, Any]:
    return {"value": None, "numerator": 0, "denominator": denominator, "status": "not_evaluable"}


def empty_metrics() -> dict[str, dict[str, Any]]:
    return {name: _empty_metric() for name in METRICS}


def _normalise_metrics(metrics: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    source = metrics or {}
    output: dict[str, dict[str, Any]] = {}
    for name in METRICS:
        value = source.get(name)
        if not isinstance(value, Mapping):
            output[name] = _empty_metric()
            continue
        numerator = value.get("numerator")
        denominator = value.get("denominator")
        if type(numerator) is not int or type(denominator) is not int:
            output[name] = _empty_metric()
            continue
        raw_value = value.get("value")
        status = value.get("status")
        output[name] = {
            "value": raw_value if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool) else None,
            "numerator": numerator,
            "denominator": denominator,
            "status": status if status in {"evaluable", "not_evaluable"} else "not_evaluable",
        }
    return output


def _terminal(run: Mapping[str, Any]) -> Mapping[str, Any]:
    terminal = run.get("terminal")
    return terminal if isinstance(terminal, Mapping) else {}


def _attempt_count(run: Mapping[str, Any]) -> int:
    attempts = run.get("attempts")
    return len(attempts) if isinstance(attempts, list) else 0


def _prediction(case_id: str, run: Mapping[str, Any]) -> dict[str, Any]:
    terminal = _terminal(run)
    return {
        "case_id": case_id,
        "state": str(terminal.get("state", "BLOCKED")),
        "candidate_induced": terminal.get("candidate_induced") if isinstance(terminal.get("candidate_induced"), bool) else None,
        "root_cause_component": terminal.get("root_cause_component") if isinstance(terminal.get("root_cause_component"), str) else None,
        "action_owner_repository": terminal.get("action_owner_repository") if isinstance(terminal.get("action_owner_repository"), str) else None,
        "substantive_experiments": _attempt_count(run),
    }


def _runs_by_case(raw: Mapping[str, Any], lane: str) -> dict[str, Mapping[str, Any]]:
    case_records = raw.get("case_records")
    if not isinstance(case_records, list) and isinstance(raw.get("harness"), Mapping):
        case_records = cast(Mapping[str, Any], raw["harness"]).get("cases", [])
    if not isinstance(case_records, list):
        case_records = raw.get("cases", [])
    opaque_to_case = {
        str(item.get("episode_id")): str(item.get("case_id"))
        for item in cast(list[Any], case_records)
        if isinstance(item, Mapping)
    }
    lane_data = raw.get("lanes", {})
    lane_data = lane_data.get(lane, {}) if isinstance(lane_data, Mapping) else {}
    runs = lane_data.get("runs", []) if isinstance(lane_data, Mapping) else []
    output: dict[str, Mapping[str, Any]] = {}
    if isinstance(runs, list):
        for item in runs:
            if not isinstance(item, Mapping) or not isinstance(item.get("run"), Mapping):
                continue
            case_id = opaque_to_case.get(str(item.get("episode_id")))
            if case_id:
                output[case_id] = cast(Mapping[str, Any], item["run"])
    return output


def _static_runs(root: Path, raw: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    labels_path = root / "corpus/v1.0.1/decisive-v1.1/evaluator-labels.json"
    static_path = root / "baselines/static-v0.4/predictions.json"
    try:
        labels = json.loads(labels_path.read_text(encoding="utf-8")).get("cases", {})
        predictions = json.loads(static_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        labels, predictions = {}, []
    by_record = {str(item.get("case_id")): item for item in predictions if isinstance(item, Mapping)}
    result: dict[str, Mapping[str, Any]] = {}
    if isinstance(labels, Mapping):
        for case_id, label in labels.items():
            source_record = label.get("source_record") if isinstance(label, Mapping) else None
            prediction = by_record.get(str(source_record), {})
            claim = prediction.get("verdict") == "confirmed_regression" and prediction.get("candidate_induced") is True
            result[str(case_id)] = {
                "terminal": {
                    "state": "CAUSALLY_ATTRIBUTED" if claim else "BOUNDED_INCONCLUSIVE",
                    "candidate_induced": prediction.get("candidate_induced") if isinstance(prediction.get("candidate_induced"), bool) else None,
                    "root_cause_component": prediction.get("root_cause_component") if claim and isinstance(prediction.get("root_cause_component"), str) else None,
                    "action_owner_repository": prediction.get("action_owner_repository") if claim and isinstance(prediction.get("action_owner_repository"), str) else None,
                },
                "attempts": [],
            }
    for case_id in SAFETY_IDS:
        result[case_id] = {"terminal": {"state": "BOUNDED_INCONCLUSIVE", "candidate_induced": None}, "attempts": []}
    return result


def case_predictions(root: Path, raw: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    runs = {
        "static-v0.4": _static_runs(root, raw),
        "naive-deterministic": _runs_by_case(raw, "naive-deterministic"),
        "agentic-v0.5-frozen": _runs_by_case(raw, "agentic-v0.5-frozen"),
    }
    output: dict[str, list[dict[str, Any]]] = {}
    for lane in LANES:
        output[lane] = [_prediction(case_id, runs[lane].get(case_id, {})) for case_id in (*HISTORICAL_IDS, *SAFETY_IDS)]
    return output


def _contract_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    baselines = result.get("baselines")
    metric_projection = {
        lane: {
            "status": item.get("status"),
            "metrics": item.get("metrics"),
        }
        for lane, item in baselines.items()
        if isinstance(baselines, Mapping)
        and isinstance(item, Mapping)
    } if isinstance(baselines, Mapping) else {}
    return {
        "cases": result.get("cases"),
        "baselines": metric_projection,
        "case_predictions": result.get("case_predictions"),
        "mandatory_case_gates": result.get("mandatory_case_gates"),
        "candidate_gold_separation": result.get("candidate_gold_separation"),
    }


def compare_reference(result: Mapping[str, Any], reference: Mapping[str, Any] | None) -> dict[str, Any]:
    if reference is None:
        return {"status": "NOT_AVAILABLE", "reference_digest": None, "mismatch_paths": []}
    left = _contract_projection(result)
    right = _contract_projection(reference)
    mismatches: list[str] = []

    def walk(a: Any, b: Any, path: str) -> None:
        if type(a) is not type(b):
            mismatches.append(path)
            return
        if isinstance(a, Mapping):
            if set(a) != set(b):
                mismatches.append(path + ".keys")
                return
            for key in sorted(a):
                walk(a[key], b[key], f"{path}.{key}")
        elif isinstance(a, list):
            if len(a) != len(b):
                mismatches.append(path + ".length")
                return
            for index, (item_a, item_b) in enumerate(zip(a, b)):
                walk(item_a, item_b, f"{path}[{index}]")
        elif a != b:
            mismatches.append(path)

    walk(left, right, "$")
    return {
        "status": "EXACT_MATCH" if not mismatches else "MISMATCH",
        "reference_digest": reference.get("_reference_digest") if isinstance(reference.get("_reference_digest"), str) else None,
        "mismatch_paths": mismatches[:100],
    }


def build_result(
    root: Path,
    *,
    raw: Mapping[str, Any] | None,
    audit: Mapping[str, Any],
    platform: Mapping[str, Any],
    reference: Mapping[str, Any] | None = None,
    reference_digest: str | None = None,
) -> dict[str, Any]:
    raw = raw or {}
    executed = int(cast(Mapping[str, Any], raw.get("cases", {})).get("executed", 0)) if isinstance(raw.get("cases"), Mapping) else 0
    blocked = 25 - executed
    blocked_cases = cast(list[dict[str, str]], cast(Mapping[str, Any], raw.get("cases", {})).get("blocked_cases", [])) if isinstance(raw.get("cases"), Mapping) else []
    lane_source = cast(Mapping[str, Any], raw.get("metrics", {})).get("lanes", {}) if isinstance(raw.get("metrics"), Mapping) else {}
    baselines: dict[str, Any] = {}
    for lane in LANES:
        item = lane_source.get(lane, {}) if isinstance(lane_source, Mapping) else {}
        baselines[lane] = {
            "status": "EXECUTED" if executed == 25 else "BLOCKED",
            "metrics": _normalise_metrics(item.get("metrics") if isinstance(item, Mapping) else None),
        }
    source_digests = cast(Mapping[str, Any], audit.get("source_digests", {}))
    baseline_digests: dict[str, str] = {}
    for item in cast(list[Any], audit.get("baseline_audit", [])):
        if isinstance(item, Mapping) and isinstance(item.get("id"), str) and isinstance(item.get("digest"), str):
            baseline_digests[str(item["id"])] = str(item["digest"])
    suite_baseline_digests: dict[str, str] = {}
    try:
        suite = json.loads((root / "corpus/v1.0.1/decisive-v1.1/suite.json").read_text(encoding="utf-8"))
        for item in suite.get("baselines", []):
            if isinstance(item, Mapping) and isinstance(item.get("id"), str) and isinstance(item.get("source_digest"), str):
                suite_baseline_digests[str(item["id"])] = str(item["source_digest"])
    except (OSError, ValueError, AttributeError):
        suite_baseline_digests = {}
    suite_baseline_digests = {
        lane: suite_baseline_digests.get(lane, baseline_digests.get(lane, "sha256:" + "0" * 64))
        for lane in LANES
    }
    provenance = {
        "suite_digest": str(source_digests.get("suite", "sha256:" + "0" * 64)),
        "historical_labels_digest": str(source_digests.get("historical_evaluator_labels", "sha256:" + "0" * 64)),
        "safety_labels_digest": str(source_digests.get("evaluator_labels", "sha256:" + "0" * 64)),
        "runtime_recipe_digest": str(cast(Mapping[str, Any], audit.get("runtime_recipes", {})).get("digest", "sha256:" + "0" * 64)),
        "baseline_digests": suite_baseline_digests,
        "platform": {"engine_os": str(platform.get("engine_os", "unknown")), "engine_architecture": str(platform.get("engine_architecture", "unknown"))},
        "execution_network": "none",
        "network_used": bool(cast(Mapping[str, Any], raw.get("harness", {})).get("network_used", False)) if isinstance(raw.get("harness"), Mapping) else False,
        "runtime_reference_used": False,
    }
    raw_metrics = cast(Mapping[str, Any], raw.get("metrics", {}))
    gates = cast(dict[str, bool], raw_metrics.get("mandatory_case_gates", {})) if isinstance(raw_metrics, Mapping) else {}
    gates = {
        "scikit-learn-30512-resolves-to-scipy": bool(gates.get("scikit-learn-30512-resolves-to-scipy", False)),
        "pandas-45601-keeps-semantic-ambiguity-open": bool(gates.get("pandas-45601-keeps-semantic-ambiguity-open", False)),
    }
    result: dict[str, Any] = {
        "schema_version": "1.1",
        "suite_id": "decisive-v1.1",
        "release_version": "1.0.1",
        "status": "COMPLETED" if executed == 25 else str(raw.get("status", "BLOCKED")),
        "certification": "UNSAFE" if executed == 25 else "INCONCLUSIVE",
        "cases": {"requested": 25, "executed": executed, "blocked": blocked, "historical": 5, "safety": 20, "blocked_cases": blocked_cases},
        "baselines": baselines,
        "case_predictions": case_predictions(root, raw),
        "mandatory_case_gates": gates,
        "canonical_reproduction": {"status": "NOT_EVALUABLE", "reference_used_as_runtime_evidence": False},
        "provenance": provenance,
        "reference_comparison": {"status": "NOT_AVAILABLE", "reference_digest": reference_digest, "mismatch_paths": []},
        "candidate_gold_separation": {"labels_loaded_after_execution": bool(raw_metrics.get("labels_loaded_after_execution", False)), "gold_visible_to_candidate": False, "historical_evidence_visible_to_candidate": False, "reference_used_as_runtime_evidence": False},
        "decision": {"executable_causal_safety": "VALIDATED_SMALL_N", "historical_attribution_executability": "VALIDATED_SMALL_N", "agentic_causal_investigation": "FAILED_DECISIVE_TEST", "cross_repository_generalization": "FAILED_DECISIVE_TEST", "product_implementation": "BLOCKED"},
    }
    if reference is not None:
        result["reference_comparison"] = compare_reference({**result, "provenance": provenance}, {**reference, "_reference_digest": reference_digest})
        result["canonical_reproduction"]["status"] = "CORRECTED_SUITE_REFERENCE_MATCH" if result["reference_comparison"]["status"] == "EXACT_MATCH" else "RESULT_MISMATCH"
    return result


def validate_result(document: Mapping[str, Any]) -> None:
    errors: list[str] = []
    cases = document.get("cases")
    if isinstance(cases, Mapping) and int(cases.get("executed", 0)) + int(cases.get("blocked", 0)) != 25:
        errors.append("cases.executed + cases.blocked must equal 25")
    baselines = document.get("baselines")
    if isinstance(baselines, Mapping):
        for lane in LANES:
            item = baselines.get(lane)
            metrics = item.get("metrics", {}) if isinstance(item, Mapping) else {}
            for name in METRICS:
                metric = metrics.get(name) if isinstance(metrics, Mapping) else None
                if not isinstance(metric, Mapping):
                    continue
                numerator = metric.get("numerator")
                denominator = metric.get("denominator")
                status = metric.get("status")
                value = metric.get("value")
                if status == "evaluable" and (not isinstance(denominator, int) or denominator <= 0):
                    errors.append(f"{lane}.{name}: evaluable metric needs a positive denominator")
                if status == "not_evaluable" and value is not None:
                    errors.append(f"{lane}.{name}: not_evaluable metric must have null value")
                if name != "median_substantive_experiments" and isinstance(numerator, int) and isinstance(denominator, int) and numerator > denominator:
                    errors.append(f"{lane}.{name}: numerator exceeds denominator")
    if errors:
        raise ValidationError("strict result contract semantic validation failed", errors)


def validate_result_document(document: Mapping[str, Any], root: Path) -> None:
    validate_json(document, "benchmark_result_v1_1", root=root)
    validate_result(document)


__all__ = [
    "LANES",
    "METRICS",
    "build_result",
    "canonical_digest",
    "compare_reference",
    "file_digest",
    "validate_result",
    "validate_result_document",
]
