"""v0.5 temporal-blind investigation episodes and replay execution.

The replay oracle is deliberately evaluator-owned.  A candidate receives an
experiment result, bounded execution evidence, and an opaque provenance id;
gold labels and future source text never cross the candidate boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from radar_bench.errors import ValidationError
from radar_bench.models.case import parse_aware
from radar_bench.schema.loader import validate_json

EXPERIMENT_TYPES = (
    "rerun", "baseline_check", "version_swap", "dependency_pin",
    "dependency_unpin", "bisect", "environment_toggle", "platform_compare",
    "architecture_compare", "artifact_source_compare", "build_variant_compare",
    "minimal_reproducer", "dependency_graph_probe",
)
ATTRIBUTABILITY_CLASSES = (
    "STATICALLY_ATTRIBUTABLE", "EXPERIMENTALLY_ATTRIBUTABLE",
    "EXTERNALLY_DEPENDENT", "UNATTRIBUTABLE",
)
TERMINAL_STATES = (
    "CAUSALLY_ATTRIBUTED", "MITIGATION_IDENTIFIED", "BOUNDED_INCONCLUSIVE",
    "EXPERIMENT_BUDGET_EXHAUSTED", "INVALID_INVESTIGATION",
)
MAX_SUBSTANTIVE_EXPERIMENTS = 5
MAX_RERUNS = 2


def canonical_digest(value: Any) -> str:
    """Hash JSON without whitespace or dictionary-order variance."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _schema_errors(value: Any, kind: str, root: Path | None) -> list[str]:
    try:
        validate_json(value, kind, root)
    except ValidationError as exc:
        return exc.errors
    return []


def validate_experiment_request(
    request: Mapping[str, Any], *, root: Path | None = None
) -> list[str]:
    """Validate schema and type-specific experiment semantics."""

    errors = _schema_errors(dict(request), "investigation_experiment_v01", root)
    if errors:
        return errors
    kind = request["type"]
    control = request.get("control")
    candidate = request.get("candidate")
    pair_required = {
        "version_swap", "dependency_pin", "dependency_unpin", "bisect",
        "environment_toggle", "platform_compare", "architecture_compare",
        "artifact_source_compare", "build_variant_compare",
    }
    if kind in pair_required:
        if not request.get("changed_variable"):
            errors.append(f"{kind} requires changed_variable")
        if not control or not candidate:
            errors.append(f"{kind} requires distinct control and candidate values")
        elif control == candidate:
            errors.append(f"{kind} control and candidate must differ")
    if kind in {"version_swap", "dependency_pin", "dependency_unpin", "bisect"}:
        if not request.get("target_component"):
            errors.append(f"{kind} requires target_component")
    if kind == "rerun" and request.get("changed_variable"):
        errors.append("rerun cannot change a variable")
    return errors


def _parse_time(value: str, name: str) -> datetime:
    return parse_aware(value, name)


def validate_episode(episode: Mapping[str, Any], *, root: Path | None = None) -> list[str]:
    errors = _schema_errors(dict(episode), "investigation_episode_v01", root)
    if errors:
        return errors
    try:
        t0 = _parse_time(episode["t0"], "t0")
        tcut = _parse_time(episode["tcut"], "tcut")
    except ValueError as exc:
        return [str(exc)]
    if tcut < t0:
        errors.append("tcut must not precede t0")
    visible = set(episode["candidate_snapshot"]["visible_evidence_ids"])
    hidden = set(episode["hidden_gold_packet"]["evidence_ids"])
    if visible & hidden:
        errors.append("candidate and hidden evidence ids must be disjoint")
    historical = episode["historical_evidence"]
    seen: set[str] = set()
    for item in historical:
        evidence_id = item["evidence_id"]
        if evidence_id in seen:
            errors.append(f"duplicate historical evidence id: {evidence_id}")
        seen.add(evidence_id)
        published = _parse_time(item["published_at"], evidence_id)
        if published < t0:
            errors.append(f"{evidence_id} precedes t0")
        if item["available_after_cutoff"] and published <= tcut:
            errors.append(f"{evidence_id} is not after tcut")
        if item["available_after_cutoff"] and item["snapshot_digest"] is None:
            errors.append(f"{evidence_id} lacks immutable snapshot digest")
    if set(episode["action_space"]) != set(EXPERIMENT_TYPES):
        errors.append("action_space must expose the complete v0.5 experiment interface")
    gold_class = episode["gold"]["attributability_class"]
    if gold_class not in ATTRIBUTABILITY_CLASSES:
        errors.append("unknown attributability class")
    if not episode["provenance"]["independent_source_ids"]:
        errors.append("episode requires independent provenance")
    return errors


def _component_candidates() -> list[dict[str, str]]:
    return [
        {"component_id": "candidate_application", "kind": "downstream", "initial_status": "plausible"},
        {"component_id": "shared_dependency", "kind": "dependency", "initial_status": "plausible"},
        {"component_id": "upstream_component", "kind": "upstream", "initial_status": "plausible"},
        {"component_id": "environment_or_service", "kind": "environment", "initial_status": "weak"},
        {"component_id": "packaging_or_artifact", "kind": "packaging", "initial_status": "weak"},
        {"component_id": "flakiness_or_infrastructure", "kind": "nondeterminism", "initial_status": "weak"},
    ]


def _classify(record: Mapping[str, Any]) -> tuple[str, str]:
    """Classify from the frozen gold evidence, never from a candidate result."""

    if record["corpus_kind"] == "safety":
        return (
            "UNATTRIBUTABLE",
            "Safety-A negative control requires abstention; no action owner is supported.",
        )
    roles = {item["role"] for item in record["source_chain"] if item["available_after_cutoff"]}
    category = record["candidate_category"]
    if category == "true_upstream_regression" and "causal_intervention" in roles:
        return (
            "EXPERIMENTALLY_ATTRIBUTABLE",
            "Gold evidence contains an immutable post-cutoff causal intervention and upstream confirmation.",
        )
    if category == "true_upstream_regression" and "resolution" in roles:
        return (
            "STATICALLY_ATTRIBUTABLE",
            "Gold evidence statically identifies an upstream resolution without a recorded causal intervention.",
        )
    return (
        "EXTERNALLY_DEPENDENT",
        "Gold evidence identifies a dependency, downstream, packaging, or expected-change boundary; owner claims are not scored as direct causal attribution.",
    )


def build_episode(record: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    """Translate one frozen v0.4 record into an evaluator-owned v0.5 episode."""

    chain = list(record["source_chain"])
    visible_chain = [item for item in chain if not item["available_after_cutoff"]]
    hidden_chain = [item for item in chain if item["available_after_cutoff"]]
    visible_ids = [item["evidence_id"] for item in visible_chain]
    hidden_ids = [item["evidence_id"] for item in hidden_chain]
    facts = [
        {
            "fact_id": item["evidence_id"],
            "text": f"Immutable public observation: {item['uri']}",
            "evidence_ids": [item["evidence_id"]],
        }
        for item in visible_chain
    ]
    if not facts:
        facts = [{
            "fact_id": f"{record['record_id']}-NO-PRE-CUT",
            "text": "No immutable resolution evidence is visible at the source cutoff.",
            "evidence_ids": [],
        }]
    gold_class, justification = _classify(record)
    label = record["label"]
    episode: dict[str, Any] = {
        "schema_version": "0.1",
        "episode_id": f"RADAR-V05-E-{record['record_id'].replace('RADAR-V04-', '')}",
        "case_id": record["record_id"],
        "corpus_kind": record["corpus_kind"],
        "difficulty": record["difficulty"],
        "t0": record["t0"],
        "tcut": record["source_cutoff"],
        "candidate_snapshot": {
            "path": record["candidate_snapshot"]["path"],
            "digest": record["candidate_snapshot"]["digest"],
            "cutoff_only": True,
            "visible_evidence_ids": visible_ids,
        },
        "hidden_gold_packet": {
            "path": record["gold_packet"]["path"],
            "digest": record["gold_packet"]["digest"],
            "post_cutoff_only": True,
            "scorer_only": True,
            "evidence_ids": hidden_ids,
        },
        "observed_facts": facts,
        "plausible_components": _component_candidates(),
        "action_space": list(EXPERIMENT_TYPES),
        "experiment_budget": {"max_substantive": MAX_SUBSTANTIVE_EXPERIMENTS, "max_reruns": MAX_RERUNS},
        "historical_evidence": [
            {key: item[key] for key in ("evidence_id", "role", "published_at", "available_after_cutoff", "immutable_source", "snapshot_digest", "uri")}
            for item in chain
        ],
        "gold": {
            "attributability_class": gold_class,
            "justification": justification,
            "source_evidence_ids": hidden_ids,
            "candidate_induced": label["candidate_induced"],
            "should_abstain": label["should_abstain"],
            "action_owner_scored": label["action_owner_scored"],
            "root_cause_component": label["root_cause_component"],
            "action_owner_repository": label["action_owner_repository"],
            "first_bad": label["first_bad"],
        },
        "terminal": {
            "candidate_induced": label["candidate_induced"],
            "root_cause_component": label["root_cause_component"],
            "action_owner_repository": label["action_owner_repository"],
            "first_bad": label["first_bad"],
            "mitigation": None,
        },
        "provenance": {
            "historical_basis": "Frozen v0.4 independently reviewed resolution-chain OSINT; no new corpus or network fetch.",
            "independent_source_ids": hidden_ids or visible_ids,
            "corpus_record_digest": record["audit"]["record_digest"],
            "episode_digest": "",
        },
    }
    episode["provenance"]["episode_digest"] = canonical_digest({key: value for key, value in episode.items() if key != "provenance"})
    errors = validate_episode(episode, root=root)
    if errors:
        raise ValidationError(f"invalid generated episode {record['record_id']}", errors)
    return episode


def build_candidate_view(episode: Mapping[str, Any]) -> dict[str, Any]:
    """Return the only episode object a candidate lane may receive."""

    return {
        "schema_version": "0.1",
        "episode_id": episode["episode_id"],
        "case_id": episode["case_id"],
        "corpus_kind": episode["corpus_kind"],
        "difficulty": episode["difficulty"],
        "t0": episode["t0"],
        "tcut": episode["tcut"],
        "candidate_snapshot": episode["candidate_snapshot"],
        "observed_facts": episode["observed_facts"],
        "plausible_components": episode["plausible_components"],
        "action_space": episode["action_space"],
        "experiment_budget": episode["experiment_budget"],
    }


class ReplayOracle:
    """Deterministic oracle over immutable post-cutoff evidence."""

    def __init__(self, episodes: Sequence[Mapping[str, Any]], *, root: Path | None = None) -> None:
        self._episodes = {item["episode_id"]: item for item in episodes}
        self._root = root
        self._counts: dict[str, int] = {}

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        errors = validate_experiment_request(request, root=self._root)
        if errors:
            return {
                "status": "INVALID",
                "request_id": request.get("request_id"),
                "error_codes": ["INVALID_REQUEST"],
                "errors": errors,
                "adapter": "historical_replay",
            }
        episode = self._episodes.get(request["episode_id"])
        if episode is None:
            return {"status": "UNAVAILABLE", "request_id": request["request_id"], "error_codes": ["UNKNOWN_EPISODE"], "adapter": "historical_replay"}
        count = self._counts.get(episode["episode_id"], 0)
        if count >= MAX_SUBSTANTIVE_EXPERIMENTS:
            return {"status": "INVALID", "request_id": request["request_id"], "error_codes": ["EXPERIMENT_BUDGET_EXHAUSTED"], "adapter": "historical_replay"}
        self._counts[episode["episode_id"]] = count + 1
        if request["type"] == "baseline_check":
            if episode["corpus_kind"] == "safety":
                return self._response(request, "BASELINE_NOT_STABLE", True, [], None, ["baseline_not_stable"], None)
            return self._response(request, "CONTROL_PASS_CANDIDATE_FAIL", True, [], None, ["environment_or_service", "flakiness_or_infrastructure"], True)
        if episode["corpus_kind"] == "safety":
            return self._response(request, "UNAVAILABLE", False, [], None, ["no_safe_causal_replay"], None)
        historical = episode["historical_evidence"]
        roles = {item["role"] for item in historical if item["available_after_cutoff"]}
        usable_roles = {"causal_intervention", "upstream_confirmation", "first_bad", "resolution"}
        if roles & usable_roles and episode["gold"]["attributability_class"] in {"STATICALLY_ATTRIBUTABLE", "EXPERIMENTALLY_ATTRIBUTABLE"}:
            evidence = [item["evidence_id"] for item in historical if item["available_after_cutoff"] and item["role"] in usable_roles]
            return self._response(
                request,
                "CANDIDATE_SPECIFIC",
                True,
                evidence,
                episode["gold"]["root_cause_component"],
                ["candidate_application", "shared_dependency", "environment_or_service"],
                True,
            )
        return self._response(request, "CONFOUNDING_DEPENDENCY", False, [], None, ["upstream_component"], True)

    @staticmethod
    def _response(
        request: Mapping[str, Any], outcome: str, useful: bool, evidence: list[str],
        component: str | None, eliminated: list[str], candidate_induced: bool | None,
    ) -> dict[str, Any]:
        return {
            "status": "AVAILABLE",
            "request_id": request["request_id"],
            "adapter": "historical_replay",
            "result": {
                "outcome": outcome,
                "useful": useful,
                "supported_component": component,
                "eliminated_hypotheses": eliminated,
                "candidate_induced": candidate_induced,
            },
            "execution_evidence": evidence,
            "provenance_id": canonical_digest({"request_id": request["request_id"], "evidence": evidence}),
        }


class HeuristicInvestigator:
    """Conservative causal planner with a five-experiment substantive budget."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root

    def run(self, view: Mapping[str, Any], oracle: Callable[[Mapping[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        phase = "OBSERVE"
        trace = [phase]
        hypotheses = [
            {"hypothesis_id": item["component_id"], "statement": f"{item['kind']} component caused the observed failure", "status": "open", "evidence_ids": [], "next_test": "baseline_check"}
            for item in view["plausible_components"]
        ]
        attempts: list[dict[str, Any]] = []
        substantive = 0
        baseline_seen = False
        terminal: dict[str, Any] | None = None
        while terminal is None:
            phase = "HYPOTHESIZE"
            trace.append(phase)
            if substantive >= MAX_SUBSTANTIVE_EXPERIMENTS:
                terminal = {"state": "EXPERIMENT_BUDGET_EXHAUSTED", "root_cause_component": None, "action_owner_repository": None, "evidence_ids": []}
                break
            phase = "SELECT_EXPERIMENT"
            trace.append(phase)
            kind = "baseline_check" if not baseline_seen else "version_swap"
            experiment_id = f"EXP-{len(attempts) + 1:02d}"
            request: dict[str, Any] = {
                "schema_version": "0.1",
                "request_id": f"REQ-{experiment_id}",
                "episode_id": view["episode_id"],
                "experiment_id": experiment_id,
                "type": kind,
                "hypothesis": "The candidate-only change explains a reproducible failure.",
                "target_component": "candidate_or_upstream" if kind == "version_swap" else None,
                "changed_variable": "candidate_revision" if kind == "version_swap" else None,
                "control": "pre-regression" if kind == "version_swap" else None,
                "candidate": "candidate" if kind == "version_swap" else None,
                "limits": {"network_policy": "denied", "timeout_seconds": 30, "memory_mb": 256, "output_mb": 10},
            }
            request_errors = validate_experiment_request(request, root=self._root)
            phase = "EXECUTE_OR_REPLAY"
            trace.append(phase)
            response = oracle(request) if not request_errors else {"status": "INVALID", "errors": request_errors, "request_id": request["request_id"], "adapter": "historical_replay"}
            substantive += 1
            phase = "UPDATE_HYPOTHESES"
            trace.append(phase)
            result = response.get("result", {})
            attempt = {
                "request": request,
                "response": response,
                "valid": response.get("status") != "INVALID",
                "available": response.get("status") == "AVAILABLE",
                "useful": bool(result.get("useful")),
                "substantive": True,
                "state_before": "SELECT_EXPERIMENT",
                "state_after": "UPDATE_HYPOTHESES",
            }
            attempts.append(attempt)
            if response.get("status") == "INVALID":
                terminal = {"state": "INVALID_INVESTIGATION", "root_cause_component": None, "action_owner_repository": None, "evidence_ids": []}
                continue
            if kind == "baseline_check":
                baseline_seen = True
                if result.get("outcome") == "BASELINE_NOT_STABLE":
                    terminal = {"state": "BOUNDED_INCONCLUSIVE", "root_cause_component": None, "action_owner_repository": None, "candidate_induced": None, "evidence_ids": []}
                    continue
                for item in hypotheses:
                    if item["hypothesis_id"] in result.get("eliminated_hypotheses", []):
                        item["status"] = "eliminated"
                        item["evidence_ids"] = response.get("execution_evidence", [])
                trace.append("HYPOTHESIZE")
                continue
            if result.get("supported_component"):
                component = result["supported_component"]
                for item in hypotheses:
                    item["status"] = "supported" if item["hypothesis_id"] == "upstream_component" else item["status"]
                    if item["status"] == "open":
                        item["status"] = "eliminated"
                terminal = {"state": "CAUSALLY_ATTRIBUTED", "root_cause_component": component, "action_owner_repository": component, "candidate_induced": result.get("candidate_induced"), "evidence_ids": response.get("execution_evidence", [])}
            else:
                terminal = {"state": "BOUNDED_INCONCLUSIVE", "root_cause_component": None, "action_owner_repository": None, "candidate_induced": result.get("candidate_induced"), "evidence_ids": []}
        return {
            "episode_id": view["episode_id"],
            "terminal": terminal,
            "phase_trace": trace,
            "hypothesis_ledger": hypotheses,
            "attempts": attempts,
            "substantive_experiments": substantive,
            "rerun_experiments": 0,
            "candidate_visible_only": True,
        }
