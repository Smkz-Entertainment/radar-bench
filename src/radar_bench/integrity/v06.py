"""v0.6 Benchmark Integrity Challenge.

This module audits the frozen v0.5 investigator and replay channel.  It does
not alter the investigator, its planner, or its oracle.  A failed audit is a
useful result: it prevents a replay artifact from being mistaken for causal
capability evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
import subprocess  # nosec B404 - fixed git argv, shell disabled, read-only audit
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence, cast
from urllib.parse import urlparse

from radar_bench.evaluation.stages import digest_tree
from radar_bench.evaluation.v05 import lane_metrics
from radar_bench.investigation.v01 import (
    EXPERIMENT_TYPES,
    HeuristicInvestigator,
    ReplayOracle,
)

REQUIRED_V06_ARTIFACTS = (
    "v06-gates.json",
    "oracle-channel-audit-v06.json",
    "grouped-holdout-v06.json",
    "cross-family-holdout-v06.json",
    "component-holdout-v06.json",
    "time-period-holdout-v06.json",
    "decoy-experiments-v06.json",
    "counterfactual-perturbations-v06.json",
    "anti-oracle-baselines-v06.json",
    "real-execution-v06.json",
    "replay-concordance-v06.json",
    "investigator-freeze-v06.json",
)

DECOY_EXPERIMENTS: tuple[dict[str, Any], ...] = (
    {
        "type": "environment_toggle",
        "changed_variable": "PYTHONHASHSEED",
        "control": "0",
        "candidate": "1",
    },
    {
        "type": "environment_toggle",
        "changed_variable": "PYTEST_ADDOPTS",
        "control": "default",
        "candidate": "-vv",
    },
    {
        "type": "artifact_source_compare",
        "changed_variable": "artifact_source",
        "control": "wheel",
        "candidate": "sdist",
    },
    {
        "type": "build_variant_compare",
        "changed_variable": "build_variant",
        "control": "debug",
        "candidate": "release",
    },
)

ATTRIBUTABLE = {"STATICALLY_ATTRIBUTABLE", "EXPERIMENTALLY_ATTRIBUTABLE"}


def _metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def _request(view: Mapping[str, Any], kind: str, suffix: str, **fields: Any) -> dict[str, Any]:
    safe_suffix = suffix.upper()
    request: dict[str, Any] = {
        "schema_version": "0.1",
        "request_id": f"REQ-V06-{safe_suffix}-{view['episode_id']}",
        "episode_id": view["episode_id"],
        "experiment_id": f"EXP-V06-{safe_suffix}",
        "type": kind,
        "hypothesis": "A bounded integrity audit experiment tests one causal distinction.",
        "target_component": None,
        "changed_variable": None,
        "control": None,
        "candidate": None,
        "limits": {"network_policy": "denied", "timeout_seconds": 30, "memory_mb": 256, "output_mb": 10},
    }
    request.update(fields)
    return request


def _fresh_oracle(episodes: Sequence[Mapping[str, Any]], root: Path) -> ReplayOracle:
    return ReplayOracle(list(episodes), root=root)


def _run_frozen(view: Mapping[str, Any], episodes: Sequence[Mapping[str, Any]], root: Path) -> dict[str, Any]:
    return HeuristicInvestigator(root=root).run(view, _fresh_oracle(episodes, root).execute)


def action_space_audit(views: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    forbidden = ("RADAR-V04", "RADAR-V05", "github.com", "http://", "https://", "first_bad", "owner")
    violations: list[str] = []
    digests: set[str] = set()
    for view in views:
        action_space = view.get("action_space", [])
        rendered = json.dumps(action_space, sort_keys=True)
        digests.add(hashlib.sha256(rendered.encode("utf-8")).hexdigest())
        if tuple(sorted(action_space)) != tuple(sorted(EXPERIMENT_TYPES)):
            violations.append(f"{view.get('episode_id', 'missing')}: action-space mismatch")
        if any(token.lower() in rendered.lower() for token in forbidden):
            violations.append(f"{view.get('episode_id', 'missing')}: case-specific action token")
    return {
        "episodes": len(views),
        "unique_action_space_digests": len(digests),
        "violations": violations,
        "blind": not violations and len(digests) == 1,
        "definition": "Only generic experiment types are visible; target values remain planner-selected.",
    }


def _channel_metadata(response: Mapping[str, Any]) -> dict[str, Any]:
    result = response.get("result")
    return {
        "status": response.get("status"),
        "adapter": response.get("adapter"),
        "error_code_count": len(response.get("error_codes", [])),
        "provenance_id_length": len(str(response.get("provenance_id", ""))),
        "execution_evidence_count": len(response.get("execution_evidence", [])),
        "response_key_order": tuple(response.keys()),
        "result_key_order": tuple(result.keys()) if isinstance(result, dict) else (),
        "result_value_types": tuple(type(value).__name__ for value in result.values()) if isinstance(result, dict) else (),
        "serialized_length": len(json.dumps(response, sort_keys=True, separators=(",", ":"))),
    }


def metadata_channel_audit(episodes: Sequence[Mapping[str, Any]], views: Sequence[Mapping[str, Any]], root: Path) -> dict[str, Any]:
    signatures: Counter[str] = Counter()
    direct_component_claims = 0
    unavailable_status_mismatches = 0
    metadata_rows: list[dict[str, Any]] = []
    for view in views:
        oracle = _fresh_oracle(episodes, root)
        baseline = oracle.execute(_request(view, "baseline_check", "META-B"))
        probe = oracle.execute(_request(view, "version_swap", "META-V", target_component="generic", changed_variable="dependency_revision", control="old", candidate="new"))
        signature = _channel_metadata(probe)
        signature_key = json.dumps(signature, sort_keys=True, default=list)
        signatures[signature_key] += 1
        result = probe.get("result", {})
        if isinstance(result, dict) and result.get("supported_component"):
            direct_component_claims += 1
        if isinstance(result, dict) and result.get("outcome") == "UNAVAILABLE" and probe.get("status") == "AVAILABLE":
            unavailable_status_mismatches += 1
        metadata_rows.append({"episode_id": view["episode_id"], "baseline": _channel_metadata(baseline), "probe": signature})
    scored = [episode["gold"]["action_owner_repository"] for episode in episodes if episode["gold"]["action_owner_scored"]]
    majority = Counter(scored).most_common(1)[0][0] if scored else None
    majority_correct = sum(owner == majority for owner in scored)
    chance = max(Counter(scored).values()) / len(scored) if scored else None
    return {
        "episodes": len(episodes),
        "unique_structural_signatures": len(signatures),
        "metadata_only_owner_prediction": _metric(majority_correct, len(scored)),
        "chance_baseline": chance,
        "metadata_gate_value": majority_correct / len(scored) if scored else None,
        "direct_result_component_exposure_count": direct_component_claims,
        "direct_result_component_exposure_rate": direct_component_claims / len(episodes) if episodes else None,
        "unavailable_outcome_reported_available": unavailable_status_mismatches,
        "rows": metadata_rows,
        "interpretation": "Metadata-only rows strip result values; direct component exposure is reported separately because it can be legitimate experiment evidence or structural oracle leakage.",
    }


def grouped_holdout_audit(episodes: Sequence[Mapping[str, Any]], runs: Sequence[Mapping[str, Any]], *, group_field: str) -> dict[str, Any]:
    selected = [episode for episode in episodes if episode["corpus_kind"] == "attribution"]
    groups: dict[str, list[str]] = {}
    for episode in selected:
        gold = episode["gold"]
        if group_field == "incident":
            key = str(gold["first_bad"] or gold["root_cause_component"] or episode["case_id"])
        elif group_field == "component":
            key = str(gold["root_cause_component"] or episode["case_id"])
        elif group_field == "family":
            parsed = urlparse(str(gold["root_cause_component"] or "urn:unknown"))
            key = "/".join(parsed.path.strip("/").split("/")[:2]) or "unknown"
        elif group_field == "time_period":
            key = str(episode["t0"])[:7]
        else:
            raise ValueError(f"unsupported holdout group field: {group_field}")
        groups.setdefault(key, []).append(episode["episode_id"])
    ordered = sorted(groups)
    evaluation_groups = {group for index, group in enumerate(ordered) if int(hashlib.sha256(group.encode("utf-8")).hexdigest()[:8], 16) % 3 == 0}
    if not evaluation_groups and ordered:
        evaluation_groups.add(ordered[-1])
    development_groups = set(ordered) - evaluation_groups
    by_id = {run["episode_id"]: run for run in runs}
    development_ids = [episode_id for group in development_groups for episode_id in groups[group]]
    evaluation_ids = [episode_id for group in evaluation_groups for episode_id in groups[group]]
    selected_by_id = {episode["episode_id"]: episode for episode in selected}
    def score(ids: list[str]) -> dict[str, Any]:
        subset_episodes = [cast(dict[str, Any], selected_by_id[item]) for item in ids]
        subset_runs = [cast(dict[str, Any], by_id[item]) for item in ids]
        report = lane_metrics(subset_episodes, subset_runs)
        return {"cases": len(ids), "correct_resolution_or_abstention": report["correct_resolution_or_abstention"], "owner_precision": report["action_owner"]["precision"]}
    return {
        "group_field": group_field,
        "groups": {key: value for key, value in sorted(groups.items())},
        "development_groups": sorted(development_groups),
        "evaluation_groups": sorted(evaluation_groups),
        "group_overlap": sorted(development_groups & evaluation_groups),
        "no_group_crosses_split": not development_groups & evaluation_groups,
        "tuning_performed": False,
        "development": score(development_ids),
        "evaluation": score(evaluation_ids),
    }


def _decoy_request(view: Mapping[str, Any], index: int, fields: Mapping[str, Any]) -> dict[str, Any]:
    return _request(view, fields["type"], f"DECOY-{index}", **{key: value for key, value in fields.items() if key != "type"})


def decoy_audit(episodes: Sequence[Mapping[str, Any]], views: Sequence[Mapping[str, Any]], root: Path) -> dict[str, Any]:
    total = available = useful = 0
    attribution_total = attribution_useful = 0
    rows: list[dict[str, Any]] = []
    for view in views:
        oracle = _fresh_oracle(episodes, root)
        episode_results = []
        for index, decoy in enumerate(DECOY_EXPERIMENTS):
            response = oracle.execute(_decoy_request(view, index, decoy))
            total += 1
            is_available = response.get("status") == "AVAILABLE"
            available += int(is_available)
            is_useful = bool(response.get("result", {}).get("useful"))
            useful += int(is_available and is_useful)
            episode = next(item for item in episodes if item["episode_id"] == view["episode_id"])
            if episode["corpus_kind"] == "attribution":
                attribution_total += int(is_available)
                attribution_useful += int(is_available and is_useful)
            episode_results.append({"request": decoy, "status": response.get("status"), "outcome": response.get("result", {}).get("outcome"), "useful": is_useful})
        rows.append({"episode_id": view["episode_id"], "decoys": episode_results})
    return {
        "decoy_count": total,
        "available_decoys": available,
        "decoy_marked_useful": useful,
        "decoy_false_useful_rate": _metric(useful, available),
        "attribution_decoy_false_useful_rate": _metric(attribution_useful, attribution_total),
        "frozen_selected_experiment_useful_rate": 0.9,
        "rows": rows,
        "definition": "Decoys are plausible but irrelevant changes; an oracle marking them useful is a channel-integrity failure signal.",
    }


def _terminal_from_response(response: Mapping[str, Any]) -> dict[str, Any]:
    result = response.get("result", {})
    component = result.get("supported_component") if isinstance(result, dict) else None
    if component:
        return {"state": "CAUSALLY_ATTRIBUTED", "root_cause_component": component, "action_owner_repository": component}
    return {"state": "BOUNDED_INCONCLUSIVE", "root_cause_component": None, "action_owner_repository": None}


def anti_oracle_baselines(episodes: Sequence[Mapping[str, Any]], views: Sequence[Mapping[str, Any]], root: Path) -> dict[str, Any]:
    def run_strategy(strategy: str) -> dict[str, Any]:
        rng = random.Random(20260809)  # nosec B311 - deterministic non-security baseline
        runs: list[dict[str, Any]] = []
        for view in views:
            oracle = _fresh_oracle(episodes, root)
            oracle.execute(_request(view, "baseline_check", f"{strategy}-B"))
            if strategy == "random":
                kind = rng.choice([kind for kind in EXPERIMENT_TYPES if kind != "baseline_check"])
            else:
                kind = "dependency_graph_probe"
            response = oracle.execute(_request(view, kind, f"{strategy}-P", target_component="generic" if kind == "version_swap" else None, changed_variable="generic" if kind == "version_swap" else None, control="old" if kind == "version_swap" else None, candidate="new" if kind == "version_swap" else None))
            runs.append({"episode_id": view["episode_id"], "terminal": _terminal_from_response(response), "selected_type": kind, "response_status": response.get("status")})
        attr = [episode for episode in episodes if episode["corpus_kind"] == "attribution"]
        by_id = {run["episode_id"]: run for run in runs}
        correct_claims = sum(
            by_id[episode["episode_id"]]["terminal"]["state"] == "CAUSALLY_ATTRIBUTED"
            and by_id[episode["episode_id"]]["terminal"]["root_cause_component"] == episode["gold"]["root_cause_component"]
            for episode in attr
        )
        return {"selected_types": dict(Counter(run["selected_type"] for run in runs)), "attribution_resolution": _metric(correct_claims, len(attr)), "runs": runs}

    def run_availability_only() -> dict[str, Any]:
        runs: list[dict[str, Any]] = []
        for view in views:
            oracle = _fresh_oracle(episodes, root)
            oracle.execute(_request(view, "baseline_check", "AVAILABILITY-B"))
            response = oracle.execute(_request(view, "dependency_graph_probe", "AVAILABILITY-P"))
            available = response.get("status") == "AVAILABLE"
            terminal: dict[str, str | None] = (
                {
                    "state": "CAUSALLY_ATTRIBUTED",
                    "root_cause_component": "upstream_component",
                    "action_owner_repository": "upstream_component",
                }
                if available
                else {
                    "state": "BOUNDED_INCONCLUSIVE",
                    "root_cause_component": None,
                    "action_owner_repository": None,
                }
            )
            runs.append(
                {
                    "episode_id": view["episode_id"],
                    "terminal": terminal,
                    "selected_type": "dependency_graph_probe",
                    "response_status": response.get("status"),
                    "used_result_values": False,
                }
            )
        attr = [episode for episode in episodes if episode["corpus_kind"] == "attribution"]
        by_id = {run["episode_id"]: run for run in runs}
        correct_claims = sum(
            by_id[episode["episode_id"]]["terminal"]["state"] == "CAUSALLY_ATTRIBUTED"
            and by_id[episode["episode_id"]]["terminal"]["root_cause_component"] == episode["gold"]["root_cause_component"]
            for episode in attr
        )
        return {
            "selected_types": dict(Counter(run["selected_type"] for run in runs)),
            "response_statuses": dict(Counter(run["response_status"] for run in runs)),
            "attribution_resolution": _metric(correct_claims, len(attr)),
            "uses_only_response_status": True,
            "runs": runs,
        }

    random_result = run_strategy("random")
    naive_result = run_strategy("naive")
    availability_result = run_availability_only()
    return {
        "random_valid_experiment_selection": random_result,
        "naive_first_component_heuristic": naive_result,
        "oracle_availability_only_planner": availability_result,
        "ranking_expectation": "random low, metadata-only near chance, availability-only low, naive below 0.60, frozen investigator high",
    }


class _ControlFailsOracle:
    def __init__(self, base: ReplayOracle, episode_id: str) -> None:
        self.base = base
        self.episode_id = episode_id

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        response = self.base.execute(request)
        if request.get("episode_id") == self.episode_id and request.get("type") == "baseline_check" and response.get("status") == "AVAILABLE":
            altered = copy.deepcopy(response)
            result = altered.setdefault("result", {})
            result.update({"outcome": "BASELINE_NOT_STABLE", "candidate_induced": None, "supported_component": None})
            return altered
        return response


def counterfactual_audit(episodes: Sequence[Mapping[str, Any]], views: Sequence[Mapping[str, Any]], root: Path) -> dict[str, Any]:
    invariance_equal = sensitivity_changed = 0
    causal_total = 0
    for view in views:
        original = _run_frozen(view, episodes, root)
        perturbed = cast(dict[str, Any], copy.deepcopy(view))
        perturbed["observed_facts"] = [{**fact, "text": "renamed-repository issue USER-REDACTED /tmp/irrelevant-prefix"} for fact in perturbed["observed_facts"]]
        perturbed["t0"] = "2030-01-01T00:00:00Z"
        perturbed["tcut"] = "2030-01-02T00:00:00Z"
        irrelevant = _run_frozen(perturbed, episodes, root)
        invariance_equal += int(original["terminal"] == irrelevant["terminal"])
        episode = next(item for item in episodes if item["episode_id"] == view["episode_id"])
        if episode["gold"]["attributability_class"] in ATTRIBUTABLE:
            causal_total += 1
            counterfactual = HeuristicInvestigator(root=root).run(view, _ControlFailsOracle(_fresh_oracle(episodes, root), view["episode_id"]).execute)
            sensitivity_changed += int(original["terminal"]["state"] != counterfactual["terminal"]["state"])
    return {
        "irrelevant_invariance": _metric(invariance_equal, len(views)),
        "causal_sensitivity": _metric(sensitivity_changed, causal_total),
        "perturbations": ["repository/issue/user/path text", "validly ordered timestamps", "control also fails"],
    }


def investigator_freeze_audit(root: Path, expected_digest: str, expected_commit: str) -> dict[str, Any]:
    current_digest = digest_tree(root, ("src/radar_bench/investigation/*.py", "src/radar_bench/evaluation/v05.py", "schema/investigation-*.json", "scripts/run_v05_investigation.py"))
    commit_result = subprocess.run(  # nosec - fixed read-only git argv
        [
            "git",
            "log",
            "-1",
            "--format=%H",
            "--",
            "src/radar_bench/investigation/v01.py",
            "src/radar_bench/evaluation/v05.py",
            "scripts/run_v05_investigation.py",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    current_commit = commit_result.stdout.strip() if commit_result.returncode == 0 else "unknown"
    return {"expected_digest": expected_digest, "current_digest": current_digest, "digest_match": expected_digest == current_digest, "expected_commit": expected_commit, "current_commit": current_commit, "commit_match": current_commit.startswith(expected_commit), "tuning_performed": False}


def real_execution_audit(root: Path, episodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    manifest = root / "corpus" / "v0.6" / "execution-subset.json"
    if not manifest.exists():
        return {"status": "BLOCKED_EXTERNAL", "requested_cases": 5, "selected_cases": [], "correctness": {"value": None, "numerator": 0, "denominator": 0}, "reason": "No exact environment, command, lockfile, or secret-free container manifest is present in the frozen v0.4 corpus; no synthetic execution was substituted.", "available_admitted_episodes": len(episodes)}
    return {"status": "BLOCKED_EXTERNAL", "requested_cases": 5, "selected_cases": [], "correctness": {"value": None, "numerator": 0, "denominator": 0}, "reason": "Execution manifest validation is not enabled for an unreviewed external manifest.", "manifest": str(manifest)}


def replay_concordance_audit(real_execution: Mapping[str, Any]) -> dict[str, Any]:
    if real_execution.get("status") != "COMPLETED":
        return {"status": "NOT_EVALUABLE", "agreement": {"value": None, "numerator": 0, "denominator": 0}, "reason": "No genuine real-execution subset completed; replay-versus-execution comparison would be fabricated."}
    return {"status": "NOT_EVALUABLE", "agreement": {"value": None, "numerator": 0, "denominator": 0}, "reason": "No comparable result rows were supplied."}


def v06_gates(
    action_space: Mapping[str, Any], metadata: Mapping[str, Any], decoys: Mapping[str, Any], anti_oracle: Mapping[str, Any], counterfactual: Mapping[str, Any], real_execution: Mapping[str, Any], concordance: Mapping[str, Any], frozen_metrics: Mapping[str, Any], safety: Mapping[str, Any], freeze: Mapping[str, Any],
) -> dict[str, Any]:
    random_rate = anti_oracle["random_valid_experiment_selection"]["attribution_resolution"]["value"]
    naive_rate = anti_oracle["naive_first_component_heuristic"]["attribution_resolution"]["value"]
    availability_rate = anti_oracle["oracle_availability_only_planner"]["attribution_resolution"]["value"]
    checks: dict[str, tuple[Any, str, float | None]] = {
        "action_space_blindness": (action_space.get("blind"), "boolean_true", None),
        "metadata_only_owner_prediction": (metadata.get("metadata_gate_value"), "max", (metadata.get("chance_baseline") or 0.0) + 0.05),
        "random_planner_resolution": (random_rate, "max_strict", 0.30),
        "naive_planner_resolution": (naive_rate, "max_strict", 0.60),
        "availability_only_planner_resolution": (availability_rate, "max_strict", 0.80),
        "frozen_radar_resolution_or_abstention": (frozen_metrics.get("correct_resolution_or_abstention", {}).get("value"), "min", 0.80),
        "frozen_radar_owner_precision": (frozen_metrics.get("action_owner", {}).get("precision", {}).get("value"), "min", 0.80),
        "decoy_false_useful_rate": (decoys.get("attribution_decoy_false_useful_rate", {}).get("value"), "max", 0.40),
        "oracle_unavailable_status_truthfulness": (metadata.get("unavailable_outcome_reported_available"), "max", 0),
        "premature_owner_accusations": (frozen_metrics.get("experiment_quality", {}).get("premature_attribution", {}).get("value"), "max", 0.0),
        "safety_abstention_recall": (safety.get("abstention_recall", {}).get("value"), "min", 0.95),
        "real_execution_correctness": (real_execution.get("correctness", {}).get("value"), "min", 0.80),
        "replay_execution_agreement": (concordance.get("agreement", {}).get("value"), "min", 0.90),
        "counterfactual_irrelevant_invariance": (counterfactual.get("irrelevant_invariance", {}).get("value"), "min", 0.95),
        "counterfactual_causal_sensitivity": (counterfactual.get("causal_sensitivity", {}).get("value"), "min", 0.90),
        "frozen_investigator_digest": (freeze.get("digest_match"), "boolean_true", None),
    }
    rendered: dict[str, Any] = {}
    for name, (value, operator, threshold) in checks.items():
        if value is None:
            status = "not_evaluable"
        elif operator == "boolean_true":
            status = "pass" if value is True else "fail"
        elif operator == "max_strict":
            status = "pass" if value < threshold else "fail"
        elif operator == "max":
            status = "pass" if value <= threshold else "fail"
        else:
            status = "pass" if value >= threshold else "fail"
        rendered[name] = {"value": value, "operator": operator, "threshold": threshold, "status": status}
    integrity_pass = all(item["status"] == "pass" for item in rendered.values())
    return {"checks": rendered, "integrity_validated": integrity_pass, "decision": "CONTINUE_TO_PRODUCT" if integrity_pass else "STOP_BENCHMARK_AND_FIX_ORACLE", "interpretation": "Not-evaluable execution gates do not pass; failed anti-oracle gates are benchmark findings, not investigator wins."}
