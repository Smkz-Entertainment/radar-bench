"""Case-agnostic executor for the decisive-v1.1 release gate.

The harness is deliberately a transport layer.  It reconstructs sealed
control/candidate runtimes, gives every lane the same opaque candidate view,
executes requests through the real runtime adapters, and only then loads the
evaluator labels for scoring.  It contains no owner or case-specific
diagnosis logic.
"""

from __future__ import annotations

import hashlib
import json
import copy
import shutil
import statistics
import subprocess  # nosec B404 - fixed Docker argv, shell disabled
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, cast

from radar_bench.execution.v07 import (
    HermeticExecutor,
    adapt_frozen_request,
    validate_request,
)
from radar_bench.execution.process import run_bounded
from radar_bench.historical_runtime import reconstruct_historical_cases
from radar_bench.investigation.v01 import (
    EXPERIMENT_TYPES,
    HeuristicInvestigator,
)

CANONICAL_PROTOCOL_VERSION = "1.1-canonical"
EVALUATOR_LABELS_RELATIVE = Path("corpus/v1.0.1/decisive-v1.1/evaluator-labels.json")
SAFETY_RUNTIME_RELATIVE = Path("corpus/v1.0.1/safety-twins/runtime-manifest.json")
STATIC_BASELINE_RELATIVE = Path("baselines/static-v0.4/predictions.json")
MAX_LABEL_BYTES = 2 * 1024 * 1024
MAX_STATIC_BYTES = 32 * 1024 * 1024
SUPPORTED_RUNTIME_CAPABILITIES = frozenset({"rerun", "change_dependency_version"})
COMPONENTS: tuple[dict[str, str], ...] = (
    {"component_id": "candidate_application", "kind": "downstream"},
    {"component_id": "shared_dependency", "kind": "dependency"},
    {"component_id": "upstream_component", "kind": "upstream"},
    {"component_id": "environment_or_service", "kind": "environment"},
    {"component_id": "packaging_or_artifact", "kind": "packaging"},
    {"component_id": "flakiness_or_infrastructure", "kind": "nondeterminism"},
)
FORBIDDEN_CANDIDATE_KEYS = frozenset(
    {
        "case_type",
        "corpus_kind",
        "evaluator_labels",
        "gold",
        "historical_evidence",
    }
)


class CandidateExecutor(Protocol):
    """The only method exposed to an investigator lane."""

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class OpaqueCase:
    """Evaluator-side case mapping; only ``candidate_view`` crosses the lane."""

    case_id: str
    episode_id: str
    lane: str
    candidate_view: dict[str, Any]


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_object(path: Path, limit: int) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"required evaluator file is absent or too large: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object in {path.name}")
    return cast(dict[str, Any], value)


def _read_list(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"required baseline file is absent or too large: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"expected a list in {path.name}")
    return [cast(dict[str, Any], item) for item in value if isinstance(item, dict)]


def _opaque_id(case_id: str) -> str:
    # The frozen v0.5 request schema owns this prefix; the suffix is opaque
    # and is identical in shape for attribution and safety cases.
    return "RADAR-V05-E-" + hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:24].upper()


def _candidate_view(episode_id: str) -> dict[str, Any]:
    """Build the identical candidate-facing shape for every lane and case."""

    return {
        "schema_version": CANONICAL_PROTOCOL_VERSION,
        "episode_id": episode_id,
        "candidate_snapshot": {
            "visible_evidence_ids": [],
            "materialization": "opaque",
        },
        "observed_facts": [
            {
                "fact_id": "sealed-runtime-interface",
                "text": "A sealed control/candidate runtime pair is available for bounded execution.",
                "evidence_ids": [],
            }
        ],
        "plausible_components": [dict(item) for item in COMPONENTS],
        "action_space": list(EXPERIMENT_TYPES),
        "experiment_budget": {"max_substantive": 5, "max_reruns": 2},
    }


def validate_candidate_view(view: Mapping[str, Any]) -> list[str]:
    """Reject evaluator-only fields before a view reaches a candidate lane."""

    errors: list[str] = []
    keys = set(view)
    forbidden = sorted(keys & FORBIDDEN_CANDIDATE_KEYS)
    if forbidden:
        errors.append("candidate view contains evaluator-only keys: " + ", ".join(forbidden))
    expected = {
        "schema_version",
        "episode_id",
        "candidate_snapshot",
        "observed_facts",
        "plausible_components",
        "action_space",
        "experiment_budget",
    }
    if keys != expected:
        errors.append("candidate view shape differs from the canonical shared protocol")
    if view.get("schema_version") != CANONICAL_PROTOCOL_VERSION:
        errors.append("candidate view has the wrong protocol version")
    return errors


def _response(
    request: Mapping[str, Any],
    control: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    adapter: str,
) -> dict[str, Any]:
    control_code = control.get("returncode")
    candidate_code = candidate.get("returncode")
    if not isinstance(control_code, int) or not isinstance(candidate_code, int):
        return {
            "status": "EXECUTION_ERROR",
            "request_id": request.get("request_id"),
            "error_codes": ["CONTAINER_EXECUTION_FAILED"],
        }
    control_pass = control_code == 0
    candidate_pass = candidate_code == 0
    if not control_pass:
        outcome = "BASELINE_NOT_STABLE"
        induced: bool | None = None
    elif control_pass != candidate_pass:
        outcome = "CANDIDATE_SPECIFIC"
        induced = not candidate_pass
    else:
        outcome = "NO_DISTINGUISHING_EFFECT"
        induced = False
    observation = {
        "control_pass": control_pass,
        "candidate_pass": candidate_pass,
        "control_output_digest": control.get("output_digest"),
        "candidate_output_digest": candidate.get("output_digest"),
    }
    return {
        "status": "COMPLETED",
        "request_id": request.get("request_id"),
        "adapter": adapter,
        "result": {
            "outcome": outcome,
            "useful": control_pass != candidate_pass,
            "supported_component": None,
            "eliminated_hypotheses": [],
            "candidate_induced": induced,
        },
        "observations": observation,
        "execution_evidence": [_canonical_digest(observation)],
        "provenance_id": _canonical_digest({"request": dict(request), "observation": observation}),
    }


class HistoricalObservationExecutor:
    """Expose completed real runtime observations through the common protocol."""

    def __init__(self, cases: Mapping[str, Mapping[str, Any]]) -> None:
        self._cases = cases

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        errors = validate_request(request)
        if errors:
            return {"status": "INVALID_REQUEST", "request_id": request.get("request_id"), "error_codes": errors}
        capability = request.get("capability")
        if capability not in SUPPORTED_RUNTIME_CAPABILITIES:
            return {
                "status": "UNSUPPORTED_EXPERIMENT",
                "request_id": request["request_id"],
                "error_codes": ["EXPERIMENT_NOT_SEALED"],
            }
        case = self._cases.get(str(request["episode_id"]))
        if case is None:
            return {"status": "EXECUTION_ERROR", "request_id": request["request_id"], "error_codes": ["CASE_NOT_SEALED"]}
        sides = case.get("sides")
        if not isinstance(sides, Mapping):
            return {"status": "EXECUTION_ERROR", "request_id": request["request_id"], "error_codes": ["CONTAINER_EXECUTION_FAILED"]}
        control = sides.get("control")
        candidate = sides.get("candidate")
        if not isinstance(control, Mapping) or not isinstance(candidate, Mapping):
            return {"status": "EXECUTION_ERROR", "request_id": request["request_id"], "error_codes": ["CONTAINER_EXECUTION_FAILED"]}
        return _response(request, control, candidate, adapter="canonical_runtime")


class OpaqueSafetyExecutor:
    """Translate opaque episode IDs to the sealed safety runtime internally."""

    def __init__(self, executor: HermeticExecutor, mapping: Mapping[str, str]) -> None:
        self._executor = executor
        self._mapping = mapping
        self._cache: dict[tuple[str, str, str], dict[str, Any]] = {}

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        errors = validate_request(request)
        if errors:
            return {"status": "INVALID_REQUEST", "request_id": request.get("request_id"), "error_codes": errors}
        original = self._mapping.get(str(request["episode_id"]))
        if original is None:
            return {"status": "EXECUTION_ERROR", "request_id": request["request_id"], "error_codes": ["CASE_NOT_SEALED"]}
        cache_key = (
            original,
            str(request["capability"]),
            json.dumps(request.get("parameters", {}), sort_keys=True, separators=(",", ":")),
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            response = copy.deepcopy(cached)
            response["request_id"] = request["request_id"]
            response["provenance_id"] = _canonical_digest(
                {"request": dict(request), "observation": response.get("observations", {})}
            )
            return response
        internal = dict(request)
        internal["episode_id"] = original
        response = self._executor.execute(internal)
        response["request_id"] = request["request_id"]
        self._cache[cache_key] = copy.deepcopy(response)
        return response


def _run_frozen(case: OpaqueCase, executor: CandidateExecutor, root: Path) -> dict[str, Any]:
    investigator = HeuristicInvestigator(root=root)
    return investigator.run(
        case.candidate_view,
        lambda request: executor.execute(adapt_frozen_request(request)),
    )


def _run_naive(case: OpaqueCase, executor: CandidateExecutor) -> dict[str, Any]:
    baseline = executor.execute(
        {
            "schema_version": "0.7",
            "request_id": f"naive-baseline-{case.episode_id}",
            "episode_id": case.episode_id,
            "capability": "rerun",
            "parameters": {},
        }
    )
    probe = executor.execute(
        {
            "schema_version": "0.7",
            "request_id": f"naive-probe-{case.episode_id}",
            "episode_id": case.episode_id,
            "capability": "change_dependency_version",
            "parameters": {"target_component": "upstream_component"},
        }
    )
    probe_result = probe.get("result", {})
    attributed = probe_result.get("outcome") == "CANDIDATE_SPECIFIC"
    terminal = {
        "state": "CAUSALLY_ATTRIBUTED" if attributed else "BOUNDED_INCONCLUSIVE",
        "root_cause_component": "upstream_component" if attributed else None,
        "action_owner_repository": "upstream_component" if attributed else None,
        "candidate_induced": probe_result.get("candidate_induced"),
        "evidence_ids": probe.get("execution_evidence", []),
    }
    return {
        "episode_id": case.episode_id,
        "terminal": terminal,
        "attempts": [
            {"request": {"capability": "rerun"}, "response": baseline, "useful": bool(baseline.get("result", {}).get("useful"))},
            {"request": {"capability": "change_dependency_version"}, "response": probe, "useful": bool(probe_result.get("useful"))},
        ],
        "substantive_experiments": 2,
        "candidate_visible_only": True,
    }


def _metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
        "status": "evaluable" if denominator else "not_evaluable",
    }


def _claim(run: Mapping[str, Any]) -> bool:
    terminal = run.get("terminal")
    return isinstance(terminal, Mapping) and terminal.get("state") == "CAUSALLY_ATTRIBUTED"


def _attempts(run: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = run.get("attempts")
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _empty_lane_metrics() -> dict[str, Any]:
    return {
        "historical_positive_resolution": _metric(0, 5),
        "candidate_induced_correctness": _metric(0, 5),
        "action_owner_correctness": _metric(0, 0),
        "cross_repository_resolution": _metric(0, 1),
        "semantic_ambiguity_handling": _metric(0, 1),
        "safety_abstention_recall": _metric(0, 20),
        "false_owner_accusation_rate": _metric(0, 20),
        "premature_owner_accusations": _metric(0, 20),
        "useful_experiment_rate": _metric(0, 0),
        "median_substantive_experiments": _metric(0, 0),
        "advantage_over_naive_positive_resolution": _metric(0, 5),
    }


def score_canonical_lanes(root: Path, run_result: Mapping[str, Any]) -> dict[str, Any]:
    """Score only after candidate lanes have returned, using evaluator files."""

    labels_document = _read_object(root / EVALUATOR_LABELS_RELATIVE, MAX_LABEL_BYTES)
    safety_document = _read_object(root / "corpus" / "v1.0.1" / "safety-twins" / "evaluator-labels.json", MAX_LABEL_BYTES)
    labels = cast(dict[str, dict[str, Any]], labels_document.get("cases", {}))
    safety_labels = cast(dict[str, dict[str, Any]], safety_document.get("cases", {}))
    opaque_cases = cast(list[dict[str, Any]], run_result.get("cases", []))
    by_lane = cast(dict[str, dict[str, Any]], run_result.get("lanes", {}))
    opaque_to_case = {str(item["episode_id"]): str(item["case_id"]) for item in opaque_cases}
    historical_ids = tuple(sorted(labels))
    safety_ids = tuple(sorted(safety_labels))

    def dynamic_runs(lane: str) -> dict[str, dict[str, Any]]:
        raw = by_lane.get(lane, {}).get("runs", [])
        return {
            opaque_to_case[str(item["episode_id"])]: cast(dict[str, Any], item["run"])
            for item in raw
            if isinstance(item, Mapping) and str(item.get("episode_id")) in opaque_to_case and isinstance(item.get("run"), Mapping)
        }

    static_predictions = cast(list[dict[str, Any]], by_lane.get("static-v0.4", {}).get("predictions", []))
    static_by_record = {str(item.get("case_id")): item for item in static_predictions}
    static_source = {
        str(case_id): str(item["source_record"])
        for case_id, item in labels.items()
        if item.get("source_record")
    }

    def static_run(case_id: str) -> dict[str, Any]:
        if case_id in labels:
            prediction = static_by_record.get(static_source.get(case_id, ""), {})
            claim = prediction.get("verdict") == "confirmed_regression" and prediction.get("candidate_induced") is True
            return {
                "terminal": {
                    "state": "CAUSALLY_ATTRIBUTED" if claim else "BOUNDED_INCONCLUSIVE",
                    "root_cause_component": prediction.get("root_cause_component") if claim else None,
                    "action_owner_repository": prediction.get("action_owner_repository") if claim else None,
                    "candidate_induced": prediction.get("candidate_induced"),
                },
                "attempts": [],
            }
        return {"terminal": {"state": "BOUNDED_INCONCLUSIVE", "candidate_induced": None}, "attempts": []}

    lanes: dict[str, dict[str, Any]] = {}
    for lane in ("static-v0.4", "naive-deterministic", "agentic-v0.5-frozen"):
        runs = {case_id: static_run(case_id) for case_id in (*historical_ids, *safety_ids)} if lane == "static-v0.4" else dynamic_runs(lane)
        metrics = _empty_lane_metrics()
        resolution = 0
        induced = 0
        owner_correct = 0
        owner_denominator = 0
        semantic = 0
        cross_repo = 0
        safety_correct = 0
        premature = 0
        useful = 0
        attempt_count = 0
        experiment_counts: list[int] = []
        for case_id in historical_ids:
            run = runs.get(case_id, {})
            label = labels[case_id]
            claim = _claim(run)
            terminal = run.get("terminal", {})
            if not isinstance(terminal, Mapping):
                terminal = {}
            if label.get("semantic_ambiguity"):
                semantic += int(not claim)
                resolution += int(not claim)
            else:
                resolution += int(claim and terminal.get("root_cause_component") == label.get("root_cause_component"))
            induced += int(terminal.get("candidate_induced") == label.get("candidate_induced"))
            if label.get("action_owner_scored") and label.get("action_owner_repository") is not None:
                owner_denominator += 1
                owner_correct += int(claim and terminal.get("action_owner_repository") == label.get("action_owner_repository"))
            if case_id == "RADAR-V07-A02":
                cross_repo = int(claim and terminal.get("root_cause_component") == label.get("root_cause_component"))
            attempts = _attempts(run)
            experiment_counts.append(len(attempts))
            attempt_count += len(attempts)
            useful += sum(int(bool(attempt.get("useful"))) for attempt in attempts)
        for case_id in safety_ids:
            run = runs.get(case_id, {})
            claim = _claim(run)
            safety_correct += int(not claim)
            premature += int(claim)
            attempts = _attempts(run)
            experiment_counts.append(len(attempts))
            attempt_count += len(attempts)
            useful += sum(int(bool(attempt.get("useful"))) for attempt in attempts)
        metrics.update(
            {
                "historical_positive_resolution": _metric(resolution, len(historical_ids)),
                "candidate_induced_correctness": _metric(induced, len(historical_ids)),
                "action_owner_correctness": _metric(owner_correct, owner_denominator),
                "cross_repository_resolution": _metric(cross_repo, 1),
                "semantic_ambiguity_handling": _metric(semantic, 1),
                "safety_abstention_recall": _metric(safety_correct, len(safety_ids)),
                "false_owner_accusation_rate": _metric(premature, len(safety_ids)),
                "premature_owner_accusations": _metric(premature, len(safety_ids)),
                "useful_experiment_rate": _metric(useful, attempt_count),
                "median_substantive_experiments": _metric(
                    int(statistics.median(experiment_counts)) if experiment_counts else 0,
                    1 if experiment_counts else 0,
                ),
            }
        )
        lanes[lane] = {"status": "EXECUTED", "metrics": metrics}
    naive_value = lanes["naive-deterministic"]["metrics"]["historical_positive_resolution"]["value"]
    frozen_value = lanes["agentic-v0.5-frozen"]["metrics"]["historical_positive_resolution"]["value"]
    lanes["agentic-v0.5-frozen"]["metrics"]["advantage_over_naive_positive_resolution"] = _metric(
        int(round((frozen_value - naive_value) * 5)) if frozen_value is not None and naive_value is not None else 0,
        5,
    )
    return {
        "schema_version": CANONICAL_PROTOCOL_VERSION,
        "labels_loaded_after_execution": True,
        "lanes": lanes,
        "mandatory_case_gates": {
            "scikit-learn-30512-resolves-to-scipy": lanes["agentic-v0.5-frozen"]["metrics"]["cross_repository_resolution"]["value"] == 1.0,
            "pandas-45601-keeps-semantic-ambiguity-open": lanes["agentic-v0.5-frozen"]["metrics"]["semantic_ambiguity_handling"]["value"] == 1.0,
        },
    }


class CanonicalHarness:
    """Prepare and execute the three decisive-v1.1 lanes."""

    def __init__(self, root: Path, artifact_root: Path | None) -> None:
        self._root = root.resolve()
        self._artifact_root = artifact_root

    def _cases(self, suite: Mapping[str, Any], safety_manifest: Mapping[str, Any]) -> list[OpaqueCase]:
        cases: list[OpaqueCase] = []
        historical = cast(list[dict[str, Any]], suite["historical_cases"])
        safety = cast(list[dict[str, Any]], safety_manifest.get("cases", []))
        for lane, entries in (("attribution", historical), ("safety", safety)):
            for entry in entries:
                case_id = str(entry["case_id"])
                episode_id = _opaque_id(case_id)
                view = _candidate_view(episode_id)
                errors = validate_candidate_view(view)
                if errors:
                    raise ValueError("invalid canonical candidate view: " + "; ".join(errors))
                cases.append(OpaqueCase(case_id, episode_id, lane, view))
        if len(cases) != 25 or len({item.episode_id for item in cases}) != 25:
            raise ValueError("decisive-v1.1 must contain 25 uniquely addressable opaque cases")
        return cases

    def _ensure_safety_image(self, manifest: Mapping[str, Any]) -> bool:
        docker = shutil.which("docker")
        if docker is None:
            raise RuntimeError("RUNTIME_UNAVAILABLE")
        cases = cast(list[dict[str, Any]], manifest.get("cases", []))
        image = str(cases[0]["platform"]["container_image"])
        inspected = run_bounded(
            [docker, "image", "inspect", image], timeout=30, max_output_bytes=64 * 1024
        )
        if inspected.returncode == 0:
            return False
        pulled = run_bounded(
            [docker, "pull", image], timeout=600, max_output_bytes=64 * 1024
        )
        if pulled.returncode != 0 or pulled.output_limit_exceeded or pulled.timed_out:
            raise RuntimeError("BASE_IMAGE_UNAVAILABLE")
        checked = run_bounded(
            [docker, "image", "inspect", image], timeout=30, max_output_bytes=64 * 1024
        )
        if checked.returncode != 0 or checked.output_limit_exceeded or checked.timed_out:
            raise RuntimeError("BASE_IMAGE_UNAVAILABLE")
        return True

    def run(self, historical_runtime: Mapping[str, Any] | None = None) -> dict[str, Any]:
        from radar_bench.release import load_suite

        suite = load_suite(self._root)
        safety_manifest = _read_object(self._root / SAFETY_RUNTIME_RELATIVE, 16 * 1024 * 1024)
        cases = self._cases(suite, safety_manifest)
        runtime = (
            dict(historical_runtime)
            if historical_runtime is not None
            else reconstruct_historical_cases(self._root, self._artifact_root)
        )
        result: dict[str, Any] = {
            "schema_version": CANONICAL_PROTOCOL_VERSION,
            "status": "BLOCKED",
            "execution_network": "none",
            "network_used": bool(runtime.get("network_used", False)),
            "historical_runtime": runtime,
            "cases": [{"case_id": item.case_id, "episode_id": item.episode_id} for item in cases],
            "lanes": {},
            "blockers": [],
        }
        if runtime.get("status") != "READY":
            result["blockers"] = list(runtime.get("blockers", [])) or ["HISTORICAL_BUILD_UNREPRODUCIBLE"]
            return result
        try:
            result["network_used"] = bool(result["network_used"] or self._ensure_safety_image(safety_manifest))
            safety_executor = OpaqueSafetyExecutor(
                HermeticExecutor(safety_manifest, root=self._root),
                {item.episode_id: item.case_id for item in cases if item.lane == "safety"},
            )
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            result["blockers"] = [str(exc) or "RUNTIME_UNAVAILABLE"]
            return result
        historical_results = {
            str(item["case_id"]): item
            for item in cast(list[dict[str, Any]], runtime.get("cases", []))
            if isinstance(item, Mapping)
        }
        historical_executor = HistoricalObservationExecutor(
            {
                item.episode_id: historical_results[item.case_id]
                for item in cases
                if item.lane == "attribution" and item.case_id in historical_results
            }
        )
        executors: dict[str, CandidateExecutor] = {"attribution": historical_executor, "safety": safety_executor}
        frozen_runs: list[dict[str, Any]] = []
        naive_runs: list[dict[str, Any]] = []
        for case in cases:
            executor = executors[case.lane]
            frozen_runs.append({"case_id": case.case_id, "episode_id": case.episode_id, "run": _run_frozen(case, executor, self._root)})
            naive_runs.append({"case_id": case.case_id, "episode_id": case.episode_id, "run": _run_naive(case, executor)})
        static_predictions = _read_list(self._root / STATIC_BASELINE_RELATIVE, MAX_STATIC_BYTES)
        result["lanes"] = {
            "static-v0.4": {"status": "EXECUTED", "predictions": static_predictions},
            "naive-deterministic": {"status": "EXECUTED", "runs": naive_runs},
            "agentic-v0.5-frozen": {"status": "EXECUTED", "runs": frozen_runs},
        }
        result["metrics"] = score_canonical_lanes(self._root, result)
        result["status"] = "COMPLETED"
        return result


__all__ = [
    "CANONICAL_PROTOCOL_VERSION",
    "CanonicalHarness",
    "EVALUATOR_LABELS_RELATIVE",
    "HistoricalObservationExecutor",
    "OpaqueCase",
    "OpaqueSafetyExecutor",
    "score_canonical_lanes",
    "validate_candidate_view",
]
