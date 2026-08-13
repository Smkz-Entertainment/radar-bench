"""Strict, case-agnostic v1.2 evaluation contracts.

The evaluator owns labels, execution receipts, and scoring.  The candidate
sees only opaque episodes and candidate-visible evidence.  This module keeps
that boundary explicit so an invalid or incomplete candidate run is a blocked
run, never an abstention score.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import secrets
import subprocess  # nosec B404 - argv is validated and shell=False is mandatory
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence, cast

V12_SUITE_ID = "decisive-v1.2"
V12_RELEASE_VERSION = "1.1.0"
V12_PROTOCOL_VERSION = "1.2-jsonl"
V12_SUITE_RELATIVE = Path("corpus/v1.1.0/decisive-v1.2/suite.json")
V12_CANDIDATE_BUNDLE_RELATIVE = Path("candidate/decisive-v1.2/candidate-bundle.json")
V12_EVALUATOR_BUNDLE_RELATIVE = Path("evaluator/decisive-v1.2/evaluator-bundle.json")
V12_EVIDENCE_RELATIVE = Path("artifacts/v1.1.0")
V12_SOLVABILITY_RELATIVE = Path("artifacts/v1.1.0/solvability-reference.json")

HISTORICAL_IDS = tuple(f"RADAR-V07-A{index:02d}" for index in range(1, 6))
SAFETY_IDS = tuple(f"RADAR-V07-T{index:02d}" for index in range(1, 21))
ALL_CASE_IDS = HISTORICAL_IDS + SAFETY_IDS
SUFFICIENCY_ROLE_EXPECTATIONS = {
    "A01_OR_OTHER": ("ATTRIBUTED", "known", "pandas"),
    "A02_SCIPY": ("ATTRIBUTED", "known", "scipy"),
    "A03_AMBIGUOUS": ("AMBIGUOUS", "ambiguous", "pandas"),
    "A04_OR_OTHER": ("ATTRIBUTED", "known", "pandas"),
    "A05_OR_OTHER": ("ATTRIBUTED", "known", "pandas"),
}
SUFFICIENCY_COMPONENT_ROLES = frozenset(SUFFICIENCY_ROLE_EXPECTATIONS)
CAPABILITIES = frozenset(
    {
        "rerun",
        "inspect_environment",
        "inspect_dependency_graph",
        "run_minimal_test",
        "change_dependency_version",
    }
)
EVIDENCE_KEYS = frozenset(
    {
        "context",
        "reproducer",
        "failure_observation",
        "control_manifest",
        "candidate_manifest",
        "package_environment_diff",
        "dependency_graph",
        "source_location_evidence",
        "platform",
        "provenance_references",
    }
)
TERMINAL_KEYS = frozenset(
    {"causal_component", "candidate_induced", "semantic_intent", "action_owner", "disposition", "evidence_ids"}
)
DISPOSITIONS = frozenset({"ATTRIBUTED", "AMBIGUOUS", "ABSTAINED"})
SEMANTIC_INTENTS = frozenset({"known", "ambiguous", "not-applicable"})
HEX64 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^[a-z0-9][a-z0-9./_-]*@sha256:[0-9a-f]{64}$")
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
FORBIDDEN_CANDIDATE_KEYS = frozenset(
    {
        "gold",
        "labels",
        "evaluator",
        "reference",
        "source_record",
        "post_cutoff",
        "semantic_intent_gold",
        "scoring_eligibility_rationale",
        "final_owner",
        "fix_commit",
        "first_bad",
        "action_owner_repository",
    }
)
FORBIDDEN_CANDIDATE_TOKENS = ("evaluator-labels", "reference/", "gold/", "gold_provenance", "historical-reproducer", "opaque-reproduction", "bounded-")
METRICS = (
    "historical_attribution_resolution",
    "historical_correct_abstention",
    "semantic_ambiguity_handling",
    "candidate_induced_correctness",
    "root_cause_component_correctness",
    "action_owner_correctness",
    "cross_repository_resolution",
    "safety_abstention_recall",
    "false_owner_accusation_rate",
    "fresh_useful_experiment_rate",
    "requested_experiment_efficiency",
)


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
        "status": "evaluable" if denominator else "not_evaluable",
    }


def empty_v12_metrics() -> dict[str, dict[str, Any]]:
    return {name: _metric(0, 0) for name in METRICS}


def generate_episode_ids(case_ids: Iterable[str] = ALL_CASE_IDS) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for case_id in case_ids:
        if case_id not in ALL_CASE_IDS:
            raise ValueError(f"unknown case ID: {case_id}")
        while True:
            episode_id = "ep_" + secrets.token_urlsafe(24)
            if episode_id not in used:
                break
        mapping[case_id] = episode_id
        used.add(episode_id)
    return mapping


def canonicalize_case_order(results: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(results, key=lambda item: str(item.get("episode_id", "")))


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> list[str]:
    return [f"{label}: unexpected fields" if set(value) != expected else ""] if set(value) != expected else []


def validate_candidate_evidence(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(evidence) != EVIDENCE_KEYS:
        errors.append("candidate evidence fields are not exactly the v1.2 set")
    for key in EVIDENCE_KEYS:
        if key not in evidence:
            continue
        value = evidence[key]
        if key in {"context", "reproducer", "failure_observation", "control_manifest", "candidate_manifest", "package_environment_diff", "dependency_graph", "platform"} and not isinstance(value, Mapping):
            errors.append(f"candidate evidence {key} must be an object")
        if key in {"source_location_evidence", "provenance_references"} and (not isinstance(value, list) or any(not isinstance(item, str) for item in value)):
            errors.append(f"candidate evidence {key} must be a string list")
    return errors


def validate_candidate_document(document: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = {"schema_version", "suite_id", "bundle_type", "evidence_schema", "cutoff_policy", "capabilities", "resource_policy", "protocol", "cases"}
    if set(document) != expected:
        errors.append("candidate bundle top-level fields are not strict")
    if document.get("schema_version") != "1.2" or document.get("suite_id") != V12_SUITE_ID:
        errors.append("candidate bundle identity is invalid")
    if document.get("bundle_type") != "candidate-visible" or document.get("evidence_schema") != "candidate-evidence-v1.2":
        errors.append("candidate bundle visibility contract is invalid")
    resource_policy = document.get("resource_policy")
    if not isinstance(resource_policy, Mapping) or set(resource_policy) != {"network", "repository_root", "evaluator_assets", "credentials"}:
        errors.append("candidate resource policy is not strict")
    protocol_policy = document.get("protocol")
    if not isinstance(protocol_policy, Mapping) or set(protocol_policy) != {"episode_start", "candidate_order", "evaluator_fields"}:
        errors.append("candidate protocol policy is not strict")
    capabilities = document.get("capabilities")
    if not isinstance(capabilities, list) or set(capabilities) != set(CAPABILITIES):
        errors.append("candidate capability set is invalid")
    cases = document.get("cases")
    if not isinstance(cases, list) or len(cases) != 25:
        errors.append("candidate bundle must contain exactly 25 cases")
        cases = []
    seen: set[str] = set()
    for item in cases:
        if not isinstance(item, Mapping) or set(item) != {"record_id", "evidence"}:
            errors.append("candidate case record is not strict")
            continue
        record_id = item.get("record_id")
        if not isinstance(record_id, str) or not re.fullmatch(r"record-\d{3}", record_id) or record_id in seen:
            errors.append("candidate record IDs must be unique strings")
        seen.add(str(record_id))
        evidence = item.get("evidence")
        if not isinstance(evidence, Mapping):
            errors.append(f"{record_id}: evidence must be an object")
        else:
            errors.extend(f"{record_id}: {error}" for error in validate_candidate_evidence(evidence))
    def visit(value: Any, path: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key)
                if key_text.lower() in FORBIDDEN_CANDIDATE_KEYS:
                    errors.append(f"evaluator-only field: {path}/{key_text}")
                visit(child, f"{path}/{key_text}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}/{index}")
        elif isinstance(value, str) and any(token in value.lower() for token in FORBIDDEN_CANDIDATE_TOKENS):
            errors.append(f"evaluator-only path token: {path}")
    visit(document)
    return errors


def metadata_shape_classifier_audit(document: Mapping[str, Any]) -> dict[str, Any]:
    """Adversarially check that historical/safety membership is not in metadata shape."""

    cases = document.get("cases")
    if not isinstance(cases, list) or len(cases) != 25:
        return {"status": "BLOCKED", "errors": ["candidate case count is not 25"]}
    signatures = []
    for item in cases:
        if not isinstance(item, Mapping) or not isinstance(item.get("evidence"), Mapping):
            continue
        signatures.append(tuple(sorted(cast(Mapping[str, Any], item["evidence"]).keys())))
    errors: list[str] = []
    if len(signatures) != 25 or len(set(signatures)) != 1:
        errors.append("candidate evidence shape differs across episodes")
    serialized = json.dumps(document, sort_keys=True).lower()
    if any(token in serialized for token in ("historical-reproducer", "opaque-reproduction", "bounded-", "safety-twin", "evaluator-labels")):
        errors.append("candidate metadata contains a case-type token")
    return {"status": "PASS" if not errors else "BLOCKED", "errors": errors, "unique_evidence_shapes": len(set(signatures))}


def validate_experiment_request(request: Mapping[str, Any]) -> list[str]:
    """Validate an untrusted request before any evaluator case lookup."""

    errors: list[str] = []
    capability = request.get("capability")
    if capability not in CAPABILITIES:
        return ["UNSUPPORTED_CAPABILITY"]
    parameters = request.get("parameters", {})
    if not isinstance(parameters, Mapping):
        return ["PARAMETERS_NOT_OBJECT"]
    required: dict[str, tuple[str, ...]] = {
        "rerun": (),
        "inspect_environment": (),
        "inspect_dependency_graph": (),
        "run_minimal_test": ("test_id",),
        "change_dependency_version": ("target_component", "version"),
    }
    allowed_parameters: dict[str, set[str]] = {
        "rerun": set(),
        "inspect_environment": set(),
        "inspect_dependency_graph": set(),
        "run_minimal_test": {"test_id"},
        "change_dependency_version": {"target_component", "version"},
    }
    errors.extend(f"UNEXPECTED_PARAMETER:{name}" for name in sorted(set(parameters) - allowed_parameters[str(capability)]))
    for name in required[str(capability)]:
        if name not in parameters or not isinstance(parameters[name], (str, int, float, bool, list)):
            errors.append(f"MISSING_PARAMETER:{name}")
    if "command" in parameters and not isinstance(parameters["command"], (str, list, tuple)):
        errors.append("INVALID_PARAMETER:command")
    if "test_id" in parameters and parameters["test_id"] != "sealed-reproducer":
        errors.append("UNSUPPORTED_TEST_ID")
    if "target_component" in parameters and not isinstance(parameters["target_component"], str):
        errors.append("INVALID_PARAMETER:target_component")
    if "version" in parameters and not isinstance(parameters["version"], str):
        errors.append("INVALID_PARAMETER:version")
    if capability == "rerun" and parameters.get("cache") is True:
        errors.append("RERUN_MUST_BE_FRESH")
    return errors


def validate_protocol_message(message: Mapping[str, Any], expected: str | None = None) -> list[str]:
    kind = message.get("message")
    if expected is not None and kind != expected:
        return [f"EXPECTED_{expected.upper()}"]
    if kind == "experiment_request":
        required = {"schema_version", "message", "episode_id", "request_id", "capability", "parameters"}
        errors = _exact_keys(message, required, "experiment_request")
        if message.get("schema_version") != V12_PROTOCOL_VERSION:
            errors.append("experiment_request schema version is invalid")
        errors.extend(validate_experiment_request(message))
        if not isinstance(message.get("episode_id"), str) or not isinstance(message.get("request_id"), str) or not message.get("request_id"):
            errors.append("experiment request IDs must be strings")
        return errors
    if kind == "final_prediction":
        required = {"schema_version", "message", "episode_id", "prediction"}
        errors = _exact_keys(message, required, "final_prediction")
        if message.get("schema_version") != V12_PROTOCOL_VERSION:
            errors.append("final_prediction schema version is invalid")
        if not isinstance(message.get("episode_id"), str) or not message.get("episode_id"):
            errors.append("final prediction episode ID must be a non-empty string")
        prediction = message.get("prediction")
        if not isinstance(prediction, Mapping):
            errors.append("prediction must be an object")
        else:
            errors.extend(validate_prediction(prediction))
        return errors
    return ["UNKNOWN_CANDIDATE_MESSAGE"]


def validate_prediction(prediction: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(prediction) != TERMINAL_KEYS:
        errors.append("terminal prediction fields are not strict")
    if prediction.get("disposition") not in DISPOSITIONS:
        errors.append("invalid terminal disposition")
    if not isinstance(prediction.get("candidate_induced"), bool):
        errors.append("candidate_induced must be boolean")
    component = prediction.get("causal_component")
    if component is not None and not isinstance(component, str):
        errors.append("causal_component must be string or null")
    if prediction.get("semantic_intent") not in SEMANTIC_INTENTS:
        errors.append("invalid semantic_intent")
    owner = prediction.get("action_owner")
    if owner is not None and not isinstance(owner, str):
        errors.append("action_owner must be string or null")
    evidence_ids = prediction.get("evidence_ids")
    if not isinstance(evidence_ids, list) or any(not isinstance(item, str) for item in evidence_ids):
        errors.append("evidence_ids must be a string list")
    return errors


@dataclass
class ExperimentLedger:
    """Evaluator-owned accounting; no ledger facts are candidate writable."""

    attempts: list[dict[str, Any]] = field(default_factory=list)
    max_experiments: int = 3

    def reject(self, request: Mapping[str, Any], error_code: str) -> dict[str, Any]:
        record: dict[str, Any] = {
            "capability": request.get("capability"),
            "request_id": request.get("request_id"),
            "requested": True,
            "valid": False,
            "executor_calls": 0,
            "fresh": False,
            "cache_hit": False,
            "reused": False,
            "available": False,
            "useful": False,
            "unsupported": error_code == "UNSUPPORTED_EXPERIMENT",
            "cleanup_verified": False,
            "error_codes": [error_code],
        }
        self.attempts.append(record)
        return record

    def run(self, request: Mapping[str, Any], executor: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> dict[str, Any]:
        if len(self.attempts) >= self.max_experiments:
            return self.reject(request, "EXPERIMENT_BUDGET_EXHAUSTED")
        errors = validate_experiment_request(request)
        record: dict[str, Any] = {
            "capability": request.get("capability"),
            "request_id": request.get("request_id"),
            "requested": True,
            "valid": not errors,
            "executor_calls": 0,
            "fresh": False,
            "cache_hit": False,
            "reused": False,
            "available": False,
            "useful": False,
            "unsupported": False,
            "cleanup_verified": False,
            "error_codes": errors,
        }
        if errors:
            self.attempts.append(record)
            return record
        record["executor_calls"] = 1
        started = time.monotonic()
        try:
            response = dict(executor(dict(request)))
        except Exception as exc:  # pragma: no cover - defensive provider boundary
            response = {"status": "EXECUTION_ERROR", "error_codes": [type(exc).__name__]}
        record["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
        record["response"] = response
        receipt = response.get("evaluator_receipt")
        if not isinstance(receipt, Mapping):
            receipt = {}
        record["available"] = bool(receipt.get("available", False))
        record["fresh"] = bool(receipt.get("fresh", False))
        record["useful"] = bool(record["fresh"] and receipt.get("useful", False))
        record["cache_hit"] = bool(receipt.get("cache_hit", False))
        record["reused"] = bool(receipt.get("reused", False))
        record["cleanup_verified"] = bool(receipt.get("cleanup_verified", False))
        record["unsupported"] = response.get("status") == "UNSUPPORTED_EXPERIMENT"
        if record["cache_hit"] or record["reused"]:
            raise ValueError("executor cannot report a cached or reused rerun")
        self.attempts.append(record)
        return record

    def summary(self) -> dict[str, Any]:
        requested = len(self.attempts)
        valid = sum(int(item["valid"]) for item in self.attempts)
        fresh = sum(int(item["fresh"]) for item in self.attempts)
        useful = sum(int(item["useful"] and item["fresh"]) for item in self.attempts)
        unavailable = sum(int(not item["available"]) for item in self.attempts)
        return {
            "requested": requested,
            "valid": valid,
            "executor_calls": sum(int(item["executor_calls"]) for item in self.attempts),
            "fresh": fresh,
            "cache_hits": sum(int(item["cache_hit"]) for item in self.attempts),
            "reused": sum(int(item["reused"]) for item in self.attempts),
            "unavailable": unavailable,
            "available": sum(int(item["available"]) for item in self.attempts),
            "unsupported": sum(int(item["unsupported"]) for item in self.attempts),
            "cleanup_verified": sum(int(item["cleanup_verified"]) for item in self.attempts),
            "useful_fresh": useful,
            "fresh_useful_experiment_rate": _metric(useful, fresh),
            "requested_experiment_efficiency": _metric(fresh, requested),
            "max_experiments": self.max_experiments,
            "budget_exhausted": requested >= self.max_experiments,
        }


def validate_label_case(case_id: str, label: Mapping[str, Any]) -> list[str]:
    expected = {"disposition", "candidate_induced", "causal_component_scored", "causal_component", "semantic_intent", "action_owner_scored", "action_owner_repository", "tcut", "scoring_eligibility_rationale", "gold_evidence_ids"}
    errors: list[str] = []
    if set(label) != expected:
        errors.append(f"{case_id}: label fields are not strict")
    if label.get("disposition") not in DISPOSITIONS:
        errors.append(f"{case_id}: invalid disposition")
    for key in ("candidate_induced", "causal_component_scored", "action_owner_scored"):
        if not isinstance(label.get(key), bool):
            errors.append(f"{case_id}: {key} must be boolean")
    if label.get("causal_component_scored") and not isinstance(label.get("causal_component"), str):
        errors.append(f"{case_id}: causal component score requires a component")
    if label.get("causal_component") is not None and not isinstance(label.get("causal_component"), str):
        errors.append(f"{case_id}: causal component must be string or null")
    if label.get("action_owner_scored") and not isinstance(label.get("action_owner_repository"), str):
        errors.append(f"{case_id}: action owner score requires a repository")
    if label.get("action_owner_repository") is not None and not isinstance(label.get("action_owner_repository"), str):
        errors.append(f"{case_id}: action owner must be string or null")
    if label.get("semantic_intent") not in SEMANTIC_INTENTS:
        errors.append(f"{case_id}: invalid semantic intent")
    if not isinstance(label.get("tcut"), str) or not ISO_UTC.fullmatch(str(label.get("tcut"))):
        errors.append(f"{case_id}: tcut must be UTC ISO-8601")
    if not isinstance(label.get("scoring_eligibility_rationale"), str) or not label.get("scoring_eligibility_rationale"):
        errors.append(f"{case_id}: scoring rationale is required")
    if not isinstance(label.get("gold_evidence_ids"), list) or not label.get("gold_evidence_ids") or any(not isinstance(item, str) for item in label.get("gold_evidence_ids", [])):
        errors.append(f"{case_id}: gold evidence IDs are required")
    return errors


def validate_label_document(document: Mapping[str, Any]) -> list[str]:
    if document.get("schema_version") != "1.2":
        return ["label document has the wrong schema version"]
    cases = document.get("cases")
    if not isinstance(cases, Mapping):
        return ["label document cases must be an object"]
    errors = [error for case_id, label in cases.items() if isinstance(label, Mapping) for error in validate_label_case(str(case_id), label)]
    errors.extend("label document case is not an object: " + str(case_id) for case_id, label in cases.items() if not isinstance(label, Mapping))
    missing = set(ALL_CASE_IDS) - {str(case_id) for case_id in cases}
    extra = {str(case_id) for case_id in cases} - set(ALL_CASE_IDS)
    if missing:
        errors.append("label document is missing cases: " + ",".join(sorted(missing)))
    if extra:
        errors.append("label document has unknown cases: " + ",".join(sorted(extra)))
    return errors


def validate_gold_provenance(document: Mapping[str, Any] | list[Any], root: Path) -> list[str]:
    records = document if isinstance(document, list) else document.get("records")
    if not isinstance(records, list):
        return ["gold provenance records must be a list"]
    by_id: dict[str, Mapping[str, Any]] = {}
    errors: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            errors.append("gold provenance record is not an object")
            continue
        record_id = record.get("evidence_id")
        digest = record.get("immutable_digest")
        archive_ref = record.get("archive_ref")
        if not isinstance(record_id, str) or record_id in by_id:
            errors.append("gold evidence IDs must be unique strings")
        if not isinstance(digest, str) or not digest.startswith("sha256:") or not HEX64.fullmatch(digest[7:]):
            errors.append(f"{record_id}: immutable digest is not a real SHA-256")
        if not isinstance(record.get("source_url"), str) or not str(record["source_url"]).startswith("https://"):
            errors.append(f"{record_id}: source URL is invalid")
        source_references = record.get("source_references")
        if not isinstance(source_references, list) or not source_references or any(
            not isinstance(value, str) or not value.startswith("https://") for value in source_references
        ):
            errors.append(f"{record_id}: source references must be non-empty HTTPS URLs")
        source_timestamps = record.get("source_reference_timestamps")
        if source_timestamps is not None:
            if not isinstance(source_timestamps, list) or len(source_timestamps) != len(source_references or []):
                errors.append(f"{record_id}: source reference timestamps do not align")
            elif any(not isinstance(value, str) or not ISO_UTC.fullmatch(value) for value in source_timestamps):
                errors.append(f"{record_id}: source reference timestamps are invalid")
        source_digests = record.get("source_reference_digests")
        if source_digests is not None:
            if not isinstance(source_digests, list) or len(source_digests) != len(source_references or []):
                errors.append(f"{record_id}: source reference digests do not align")
            elif any(not isinstance(value, str) or not HEX64.fullmatch(value.removeprefix("sha256:")) for value in source_digests):
                errors.append(f"{record_id}: source reference digests are invalid")
        if not isinstance(record.get("tcut"), str) or not ISO_UTC.fullmatch(str(record.get("tcut"))):
            errors.append(f"{record_id}: tcut is invalid")
        archive_path: Path | None = None
        if isinstance(archive_ref, str):
            archive_path = (root / archive_ref).resolve()
            try:
                archive_path.relative_to(root.resolve())
            except ValueError:
                archive_path = None
        if archive_path is None or not archive_path.is_file():
            errors.append(f"{record_id}: archive reference is absent")
        elif isinstance(digest, str) and file_digest(archive_path) != digest:
            errors.append(f"{record_id}: immutable digest does not match archive reference")
        if isinstance(record_id, str):
            by_id[record_id] = record
    return errors


def score_v12(labels: Mapping[str, Mapping[str, Any]], runs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    errors = validate_label_document({"schema_version": "1.2", "cases": labels})
    if errors:
        raise ValueError("invalid v1.2 labels: " + "; ".join(errors))
    metrics = empty_v12_metrics()
    hist_resolution = hist_abstention = semantic = induced = root = owner = cross = 0
    root_denominator = owner_denominator = attribution_denominator = abstention_denominator = 0
    safety_abstention = false_owner = safety_denominator = 0
    useful = fresh = requested = 0
    for case_id in ALL_CASE_IDS:
        label = labels[case_id]
        run = runs.get(case_id)
        prediction = run.get("prediction") if isinstance(run, Mapping) else None
        prediction = prediction if isinstance(prediction, Mapping) else {}
        disposition = prediction.get("disposition")
        if case_id in HISTORICAL_IDS:
            if label["disposition"] == "ATTRIBUTED":
                attribution_denominator += 1
                hist_resolution += int(
                    disposition == "ATTRIBUTED"
                    and (
                        not label["causal_component_scored"]
                        or prediction.get("causal_component") == label["causal_component"]
                    )
                )
            elif label["disposition"] == "ABSTAINED":
                abstention_denominator += 1
                hist_abstention += int(disposition == "ABSTAINED")
            if label["semantic_intent"] == "ambiguous":
                semantic += int(prediction.get("semantic_intent") == "ambiguous" and disposition == "AMBIGUOUS")
            induced += int(prediction.get("candidate_induced") is label["candidate_induced"])
            if label["causal_component_scored"]:
                root_denominator += 1
                root += int(prediction.get("causal_component") == label["causal_component"])
            if label["action_owner_scored"]:
                owner_denominator += 1
                owner += int(prediction.get("action_owner") == label["action_owner_repository"])
            if case_id == "RADAR-V07-A02":
                cross += int(prediction.get("causal_component") == "scipy" and disposition == "ATTRIBUTED")
        else:
            safety_denominator += int(label["disposition"] == "ABSTAINED")
            safety_abstention += int(label["disposition"] == "ABSTAINED" and disposition == "ABSTAINED")
        if prediction.get("action_owner") is not None and not label["action_owner_scored"]:
            false_owner += 1
        ledger = run.get("ledger") if isinstance(run, Mapping) else None
        attempts = ledger.get("attempts", []) if isinstance(ledger, Mapping) else run.get("attempts", []) if isinstance(run, Mapping) else []
        if isinstance(attempts, list):
            for attempt in attempts:
                if isinstance(attempt, Mapping):
                    requested += int(attempt.get("requested", True))
                    fresh += int(attempt.get("fresh", False))
                    useful += int(attempt.get("useful", False) and attempt.get("fresh", False))
    metrics.update(
        {
            "historical_attribution_resolution": _metric(hist_resolution, attribution_denominator),
            "historical_correct_abstention": _metric(hist_abstention, abstention_denominator),
            "semantic_ambiguity_handling": _metric(semantic, sum(int(labels[item]["semantic_intent"] == "ambiguous") for item in HISTORICAL_IDS)),
            "candidate_induced_correctness": _metric(induced, len(HISTORICAL_IDS)),
            "root_cause_component_correctness": _metric(root, root_denominator),
            "action_owner_correctness": _metric(owner, owner_denominator),
            "cross_repository_resolution": _metric(cross, 1),
            "safety_abstention_recall": _metric(safety_abstention, safety_denominator),
            "false_owner_accusation_rate": _metric(
                false_owner,
                sum(int(not labels[case_id]["action_owner_scored"]) for case_id in ALL_CASE_IDS),
            ),
            "fresh_useful_experiment_rate": _metric(useful, fresh),
            "requested_experiment_efficiency": _metric(fresh, requested),
        }
    )
    return {"schema_version": V12_PROTOCOL_VERSION, "metrics": metrics}


def validate_v12_result_document(document: Mapping[str, Any], root: Path | None = None) -> list[str]:
    """Validate the emitted v1.2 result shape, including blocked results."""

    allowed = {
        "schema_version", "suite_id", "release_version", "status", "candidate_gold_visible",
        "candidate_repository_visible", "network_used", "episode_ids", "candidate_bundle",
        "runtime", "artifact_root", "blockers", "information_sufficiency", "evaluator_bundle",
        "protocol", "protocol_result", "runs", "episode_count", "mapping_digest", "metrics",
        "candidate_bundle_digest", "evaluator_bundle_digest", "runtime_digest", "artifact_catalog_digest",
        "baseline_digests", "protocol_version", "executor_capability_version", "platform_contract",
        "isolation_verification", "experiment_receipts", "predictions", "source_provenance",
        "cleanup_status", "decision", "scientific_classification",
    }
    required = {"schema_version", "suite_id", "release_version", "status", "candidate_gold_visible", "candidate_repository_visible", "network_used", "blockers"}
    errors: list[str] = []
    if set(document) - allowed:
        errors.append("v1.2 result contains unexpected fields")
    if not required.issubset(document):
        errors.append("v1.2 result is missing required fields")
    if document.get("schema_version") != V12_PROTOCOL_VERSION or document.get("suite_id") != V12_SUITE_ID:
        errors.append("v1.2 result identity is invalid")
    if document.get("release_version") != V12_RELEASE_VERSION:
        errors.append("v1.2 result release version is invalid")
    if document.get("status") not in {"BLOCKED", "COMPLETED"}:
        errors.append("v1.2 result status is invalid")
    if document.get("candidate_gold_visible") is not False or document.get("candidate_repository_visible") is not False or document.get("network_used") is not False:
        errors.append("v1.2 result isolation flags are invalid")
    blockers = document.get("blockers")
    if not isinstance(blockers, list) or any(not isinstance(item, str) for item in blockers):
        errors.append("v1.2 result blockers must be a string list")
    if document.get("status") == "COMPLETED":
        required_completed = {
            "candidate_bundle_digest", "evaluator_bundle_digest", "runtime_digest", "artifact_catalog_digest",
            "baseline_digests", "protocol_version", "executor_capability_version", "platform_contract",
            "isolation_verification", "experiment_receipts", "predictions", "source_provenance",
            "cleanup_status", "decision", "scientific_classification",
        }
        if not required_completed.issubset(document):
            errors.append("completed v1.2 result is missing provenance or execution fields")
        if blockers != []:
            errors.append("completed v1.2 result cannot contain blockers")
        if document.get("episode_count") != len(ALL_CASE_IDS) or not isinstance(document.get("runs"), Mapping):
            errors.append("completed v1.2 result must contain all 25 runs")
        else:
            runs = cast(Mapping[str, Any], document["runs"])
            if set(runs) != set(ALL_CASE_IDS):
                errors.append("completed v1.2 result runs are not exactly the canonical 25 cases")
            for case_id, run in runs.items():
                if not isinstance(run, Mapping) or not isinstance(run.get("prediction"), Mapping):
                    errors.append(f"completed run is malformed: {case_id}")
                elif validate_prediction(cast(Mapping[str, Any], run["prediction"])):
                    errors.append(f"completed prediction is invalid: {case_id}")
        protocol = document.get("protocol")
        if not isinstance(protocol, Mapping) or protocol.get("version") != V12_PROTOCOL_VERSION or protocol.get("network_denied") is not True or protocol.get("docker_isolated") is not True:
            errors.append("completed v1.2 result lacks network-denied protocol evidence")
        metrics = document.get("metrics")
        if not isinstance(metrics, Mapping) or set(metrics) != set(METRICS):
            errors.append("completed v1.2 result metrics are incomplete")
        predictions = document.get("predictions")
        if not isinstance(predictions, Mapping) or set(predictions) != set(ALL_CASE_IDS):
            errors.append("completed v1.2 result predictions are not exactly the canonical 25 cases")
        else:
            for case_id, prediction in predictions.items():
                if not isinstance(prediction, Mapping) or validate_prediction(cast(Mapping[str, Any], prediction)):
                    errors.append(f"completed prediction map is malformed: {case_id}")
        receipts = document.get("experiment_receipts")
        if not isinstance(receipts, Mapping) or set(receipts) != set(ALL_CASE_IDS) or any(not isinstance(value, Mapping) for value in receipts.values()):
            errors.append("completed v1.2 result experiment receipts are incomplete")
        for field in ("candidate_bundle_digest", "evaluator_bundle_digest", "runtime_digest", "artifact_catalog_digest", "mapping_digest"):
            if not isinstance(document.get(field), str) or not HEX64.fullmatch(str(document[field]).removeprefix("sha256:")):
                errors.append(f"completed v1.2 result digest is invalid: {field}")
        baseline_digests = document.get("baseline_digests")
        if not isinstance(baseline_digests, Mapping) or not baseline_digests or any(not isinstance(value, str) or not HEX64.fullmatch(value.removeprefix("sha256:")) for value in baseline_digests.values()):
            errors.append("completed v1.2 result baseline digests are invalid")
        platform = document.get("platform_contract")
        if not isinstance(platform, Mapping) or set(platform) != {"os", "architecture", "runtime", "network"} or platform.get("network") != "none":
            errors.append("completed v1.2 result platform contract is invalid")
        isolation = document.get("isolation_verification")
        if not isinstance(isolation, Mapping) or any(isolation.get(key) is not True for key in ("candidate_gold_hidden", "candidate_repository_hidden", "network_denied", "cleanup_verified")):
            errors.append("completed v1.2 result isolation verification is incomplete")
        provenance = document.get("source_provenance")
        if not isinstance(provenance, Mapping) or any(not isinstance(provenance.get(key), str) for key in ("suite", "candidate_bundle", "evaluator_bundle", "runtime", "artifact_catalog", "baseline")):
            errors.append("completed v1.2 result source provenance is incomplete")
        cleanup = document.get("cleanup_status")
        if not isinstance(cleanup, Mapping) or any(cleanup.get(key) != "VERIFIED" for key in ("candidate_container", "experiment_containers", "preparation_volumes")):
            errors.append("completed v1.2 result cleanup status is not verified")
    return errors


@dataclass(frozen=True)
class CandidatePacket:
    episode_id: str
    evidence: Mapping[str, Any]
    capabilities: tuple[str, ...]
    budget: Mapping[str, int] = field(default_factory=lambda: {"max_experiments": 3})

    def as_json(self) -> dict[str, Any]:
        return {
            "schema_version": V12_PROTOCOL_VERSION,
            "message": "episode_start",
            "episode_id": self.episode_id,
            "candidate_evidence": dict(self.evidence),
            "capabilities": list(self.capabilities),
            "budget": dict(self.budget),
        }


def validate_record_case_mapping(mapping: Mapping[str, Any]) -> list[str]:
    expected_records = {f"record-{index:03d}" for index in range(1, 26)}
    if set(mapping) != expected_records:
        return ["record-to-case mapping must contain exactly record-001 through record-025"]
    values = [mapping[key] for key in sorted(mapping)]
    if any(not isinstance(value, str) or value not in ALL_CASE_IDS for value in values):
        return ["record-to-case mapping contains an unknown case ID"]
    if len(set(values)) != len(ALL_CASE_IDS):
        return ["record-to-case mapping must be bijective"]
    return []


def build_candidate_packets(
    candidate_document: Mapping[str, Any],
    record_case_mapping: Mapping[str, Any],
    case_to_episode: Mapping[str, str],
    *,
    randomizer: Any | None = None,
) -> list[CandidatePacket]:
    """Bind opaque records to cases on the evaluator side before shuffling.

    The candidate never receives ``record_id`` or ``case_id``.  Keeping the
    pair together before randomization prevents independent-list shuffles from
    corrupting the evaluator's gold alignment.
    """

    errors = validate_record_case_mapping(record_case_mapping)
    if errors:
        raise ValueError("; ".join(errors))
    raw_cases = candidate_document.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != len(ALL_CASE_IDS):
        raise ValueError("candidate document does not contain 25 case records")
    bound: list[tuple[str, Mapping[str, Any]]] = []
    for item in raw_cases:
        if not isinstance(item, Mapping) or not isinstance(item.get("record_id"), str) or not isinstance(item.get("evidence"), Mapping):
            raise ValueError("candidate case record is malformed")
        record_id = str(item["record_id"])
        case_id = record_case_mapping.get(record_id)
        if not isinstance(case_id, str) or case_id not in case_to_episode:
            raise ValueError(f"record has no evaluator episode binding: {record_id}")
        bound.append((case_id, cast(Mapping[str, Any], item["evidence"])))
    if len({case_id for case_id, _ in bound}) != len(ALL_CASE_IDS):
        raise ValueError("candidate records do not cover all cases exactly once")
    (randomizer or secrets.SystemRandom()).shuffle(bound)
    return [
        CandidatePacket(case_to_episode[case_id], evidence, tuple(sorted(CAPABILITIES)))
        for case_id, evidence in bound
    ]


def build_candidate_docker_argv(image: str, candidate_argv: Sequence[str], container_name: str, resource_mount: tuple[Path, str] | None = None) -> list[str]:
    if not IMAGE_DIGEST.fullmatch(image):
        raise ValueError("candidate image must be pinned by a full sha256 digest")
    if not container_name or not re.fullmatch(r"radar-candidate-[a-z0-9-]+", container_name):
        raise ValueError("invalid candidate container name")
    if not candidate_argv or any(not isinstance(item, str) or not item for item in candidate_argv):
        raise ValueError("candidate argv must be a non-empty string list")
    argv = ["docker", "run", "-i", "--rm", "--name", container_name, "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65532:65532", "--memory=512m", "--memory-swap=512m", "--cpus=1", "--pids-limit=128", "--ulimit", "nofile=1024:1024", "--ulimit", "core=0:0", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777"]  # nosec B108 - container-local tmpfs, never a host path
    if resource_mount is not None:
        host_path, container_path = resource_mount
        if not host_path.is_absolute() or not container_path.startswith("/") or container_path == "/":
            raise ValueError("resource mount must be an explicit absolute candidate-only path")
        argv.extend(["--mount", f"type=bind,src={host_path},dst={container_path},readonly"])
    argv.extend(["--env", "LANG=C", "--env", "LC_ALL=C", image])
    argv.extend(candidate_argv)
    return argv


def validate_sandbox_argv(argv: Sequence[str]) -> list[str]:
    lowered = [str(item).lower() for item in argv]
    errors: list[str] = []
    required = ("--network=none", "--read-only", "--cap-drop=all", "--security-opt=no-new-privileges", "--user=65532:65532", "--memory=512m", "--memory-swap=512m", "--cpus=1", "--pids-limit=128", "--tmpfs")
    for flag in required:
        if flag not in lowered:
            errors.append(f"missing sandbox flag: {flag}")
    forbidden = ("--privileged", "--network=host", "--pid=host", "--ipc=host", "--uts=host", "/var/run/docker.sock", "--device")
    errors.extend(f"forbidden sandbox flag: {flag}" for flag in forbidden if flag in lowered)
    if lowered.count("--network=none") != 1 or lowered.count("--read-only") != 1 or lowered.count("--cap-drop=all") != 1:
        errors.append("duplicate isolation flag")
    return errors


def verify_actual_container_config(inspect_document: Mapping[str, Any]) -> list[str]:
    if not isinstance(inspect_document.get("HostConfig"), Mapping) or not isinstance(inspect_document.get("Config"), Mapping):
        return ["docker inspect document is incomplete"]
    host = cast(Mapping[str, Any], inspect_document["HostConfig"])
    config = cast(Mapping[str, Any], inspect_document["Config"])
    errors: list[str] = []
    if host.get("NetworkMode") != "none" or host.get("ReadonlyRootfs") is not True:
        errors.append("network or root filesystem isolation is not proven")
    if host.get("Privileged") is True or host.get("CapDrop") not in (["ALL"], ["all"]):
        errors.append("privilege/capability isolation is not proven")
    security = host.get("SecurityOpt", [])
    if not isinstance(security, list) or not any(str(item).lower().startswith("no-new-privileges") for item in security):
        errors.append("no-new-privileges is not proven")
    if str(config.get("User", "")) not in {"65532", "65532:65532"}:
        errors.append("non-root user is not proven")
    if host.get("Memory") != 512 * 1024 * 1024:
        errors.append("memory limit is not 512 MiB")
    if host.get("MemorySwap") != 512 * 1024 * 1024:
        errors.append("memory swap limit is not 512 MiB")
    if host.get("PidsLimit") != 128:
        errors.append("PID limit is not 128")
    if host.get("NanoCpus") != 1_000_000_000 and host.get("CpuQuota") != 100_000:
        errors.append("CPU limit is not one CPU")
    if host.get("PidMode") not in (None, "", False) or host.get("UTSMode") not in (None, "", False) or host.get("UsernsMode") not in (None, "", False) or host.get("IpcMode") not in (None, "", False, "private"):
        errors.append("host namespaces are not permitted")
    if host.get("Devices") not in (None, []):
        errors.append("devices are not permitted")
    mounts = inspect_document.get("Mounts", [])
    if not isinstance(mounts, list):
        errors.append("mount inspection is incomplete")
    else:
        for mount in mounts:
            if not isinstance(mount, Mapping):
                errors.append("mount inspection contains an invalid entry")
                continue
            if mount.get("Type") in {"bind", "volume"}:
                errors.append("host or named-volume mounts are not permitted")
            if str(mount.get("Source", "")).lower().endswith(("docker.sock", "docker_engine")):
                errors.append("Docker socket mount is not permitted")
    return errors


class ExternalCandidateProtocol:
    """Stateful JSONL protocol executed only through the hardened Docker argv."""

    def __init__(self, candidate_image: str | Sequence[str], candidate_argv: Sequence[str] | None = None, *, working_directory: Path, timeout_seconds: float = 30.0, max_line_bytes: int = 256 * 1024, max_stdout_bytes: int = 4 * 1024 * 1024, max_stderr_bytes: int = 4 * 1024 * 1024, max_total_output_bytes: int = 8 * 1024 * 1024) -> None:
        self.working_directory = working_directory.resolve()
        self.timeout_seconds = timeout_seconds
        self.max_line_bytes = max_line_bytes
        self.max_stdout_bytes = max_stdout_bytes
        self.max_stderr_bytes = max_stderr_bytes
        self.max_total_output_bytes = max_total_output_bytes
        self.legacy_command = isinstance(candidate_image, Sequence) and not isinstance(candidate_image, str) and candidate_argv is None
        if self.legacy_command:
            self.command = tuple(str(item) for item in candidate_image)
        else:
            if not isinstance(candidate_image, str) or candidate_argv is None:
                raise ValueError("candidate image and candidate argv are required")
            container_name = "radar-candidate-" + secrets.token_hex(8)
            self.command = tuple(build_candidate_docker_argv(candidate_image, candidate_argv, container_name))
        self.container_name = self._container_name()
        if not self.command:
            raise ValueError("candidate command is empty")

    @property
    def docker_isolated(self) -> bool:
        return not self.legacy_command and not validate_sandbox_argv(self.command) and Path(self.command[0]).name.lower() in {"docker", "docker.exe"}

    def _container_name(self) -> str | None:
        try:
            index = self.command.index("--name")
            value = self.command[index + 1]
            return value if value.startswith("radar-candidate-") else None
        except (ValueError, IndexError):
            return None

    def _cleanup_container(self) -> bool:
        if self.container_name is None:
            return False
        docker = self.command[0]
        try:
            first = subprocess.run([docker, "inspect", self.container_name], capture_output=True, check=False, shell=False, timeout=5)  # nosec B603
            if first.returncode != 0:
                stderr = first.stderr.decode("utf-8", "replace").lower()
                return "no such object" in stderr or "no such container" in stderr
            removed = subprocess.run([docker, "rm", "-f", self.container_name], capture_output=True, check=False, shell=False, timeout=5)  # nosec B603
            if removed.returncode != 0:
                return False
            final = subprocess.run([docker, "inspect", self.container_name], capture_output=True, check=False, shell=False, timeout=5)  # nosec B603
            stderr = final.stderr.decode("utf-8", "replace").lower()
            return final.returncode != 0 and ("no such object" in stderr or "no such container" in stderr)
        except (OSError, subprocess.SubprocessError):
            return False

    def _actual_container_config(self) -> list[str]:
        if self.container_name is None:
            return ["candidate container name is unavailable"]
        try:
            last_error = "running candidate container could not be inspected"
            for _ in range(20):
                completed = subprocess.run(  # nosec B603 - Docker argv is fixed
                    [self.command[0], "inspect", self.container_name],
                    capture_output=True,
                    check=False,
                    shell=False,
                    timeout=5,
                )
                if completed.returncode == 0:
                    value = json.loads(completed.stdout.decode("utf-8"))
                    if not isinstance(value, list) or not value or not isinstance(value[0], Mapping):
                        return ["docker inspect returned no candidate container"]
                    return verify_actual_container_config(cast(Mapping[str, Any], value[0]))
                time.sleep(0.05)
            return [last_error]
        except (OSError, subprocess.SubprocessError, ValueError, UnicodeError) as exc:
            return [f"candidate container inspect failed: {type(exc).__name__}"]

    def run(self, packets: Iterable[CandidatePacket], experiment_executor: Callable[[str, Mapping[str, Any]], Mapping[str, Any]] | None = None) -> dict[str, Any]:
        packet_list = list(packets)
        if not self.working_directory.is_dir():
            return {"status": "BLOCKED", "error": "CANDIDATE_WORKSPACE_ABSENT"}
        if not self.docker_isolated:
            return {"status": "BLOCKED", "error": "CANDIDATE_ISOLATION_NOT_PROVEN", "network_denied": False}
        if len(packet_list) != len(ALL_CASE_IDS) or len({packet.episode_id for packet in packet_list}) != len(packet_list):
            return {"status": "BLOCKED", "error": "CANDIDATE_CASE_SET_INVALID", "network_denied": False}
        safe_env = {"PATH": os.environ.get("PATH", ""), "LANG": "C", "LC_ALL": "C", "RADAR_BENCH_EXTERNAL_CANDIDATE": "1"}
        try:
            process = subprocess.Popen(list(self.command), cwd=self.working_directory, env=safe_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)  # nosec B603
        except OSError as exc:
            return {"status": "BLOCKED", "error": "CANDIDATE_PROCESS_UNAVAILABLE", "detail": type(exc).__name__}
        frames: queue.Queue[bytes | None] = queue.Queue(maxsize=32)
        overflow = threading.Event()
        output_state = {"total": 0, "stdout": 0, "stderr": 0}
        output_lock = threading.Lock()
        partial_frame = threading.Event()

        def read_stdout() -> None:
            if process.stdout is None:
                overflow.set()
                return
            buffer = bytearray()
            try:
                while not overflow.is_set():
                    chunk = os.read(process.stdout.fileno(), 64 * 1024)
                    if not chunk:
                        break
                    with output_lock:
                        output_state["total"] += len(chunk)
                        output_state["stdout"] += len(chunk)
                        if output_state["stdout"] > self.max_stdout_bytes or output_state["total"] > self.max_total_output_bytes:
                            overflow.set()
                            break
                    buffer.extend(chunk)
                    while b"\n" in buffer:
                        frame, _, remainder = buffer.partition(b"\n")
                        buffer = bytearray(remainder)
                        if len(frame) > self.max_line_bytes:
                            overflow.set()
                            return
                        try:
                            frames.put(bytes(frame), timeout=0.1)
                        except queue.Full:
                            overflow.set()
                            return
                    if len(buffer) > self.max_line_bytes:
                        overflow.set()
                        return
                if buffer and not overflow.is_set():
                    partial_frame.set()
            except (OSError, queue.Full):
                overflow.set()
            finally:
                try:
                    frames.put(None, timeout=0.1)
                except queue.Full:
                    overflow.set()

        def drain_stderr() -> None:
            if process.stderr is None:
                overflow.set()
                return
            try:
                while True:
                    chunk = os.read(process.stderr.fileno(), 64 * 1024)
                    if not chunk:
                        return
                    with output_lock:
                        output_state["total"] += len(chunk)
                        output_state["stderr"] += len(chunk)
                        if output_state["stderr"] > self.max_stderr_bytes or output_state["total"] > self.max_total_output_bytes:
                            overflow.set()
                            return
            except OSError:
                overflow.set()

        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=drain_stderr, daemon=True).start()
        mapping = {packet.episode_id: packet for packet in packet_list}
        finals: dict[str, dict[str, Any]] = {}
        ledgers: dict[str, ExperimentLedger] = {
            packet.episode_id: ExperimentLedger(max_experiments=max(0, int(packet.budget.get("max_experiments", 3))))
            for packet in packet_list
        }
        finalized: set[str] = set()
        errors: list[str] = []
        try:
            inspect_errors = self._actual_container_config()
            if inspect_errors:
                errors.extend(["CANDIDATE_ACTUAL_CONFIG_INVALID", *inspect_errors])
                return {"status": "BLOCKED", "network_denied": False, "predictions": {}, "ledgers": {}, "errors": errors}
            if process.stdin is None:
                errors.append("CANDIDATE_PROCESS_STDIN_UNAVAILABLE")
                return {"status": "BLOCKED", "network_denied": False, "predictions": {}, "ledgers": {}, "errors": errors}
            for packet in packet_list:
                process.stdin.write((json.dumps(packet.as_json(), sort_keys=True) + "\n").encode("utf-8"))
            process.stdin.flush()
            deadline = time.monotonic() + self.timeout_seconds
            ended = False
            while time.monotonic() < deadline and len(finals) < len(packet_list):
                if overflow.is_set():
                    errors.append("CANDIDATE_OUTPUT_LIMIT")
                    break
                try:
                    frame = frames.get(timeout=max(0.01, min(0.25, deadline - time.monotonic())))
                except queue.Empty:
                    if process.poll() is not None:
                        ended = True
                        break
                    continue
                if frame is None:
                    ended = True
                    break
                try:
                    message = json.loads(frame.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    errors.append("CANDIDATE_NON_JSON_OUTPUT")
                    continue
                if not isinstance(message, dict):
                    errors.append("CANDIDATE_RESPONSE_NOT_OBJECT")
                    continue
                episode_id = message.get("episode_id")
                if episode_id not in mapping:
                    errors.append("UNKNOWN_EPISODE_ID")
                    continue
                message_errors = validate_protocol_message(message)
                if message_errors:
                    errors.extend(message_errors)
                    continue
                if message["message"] == "experiment_request":
                    request_id = str(message["request_id"])
                    episode_key = str(episode_id)
                    ledger = ledgers[episode_key]
                    if any(item.get("request_id") == request_id for item in ledger.attempts):
                        errors.append("DUPLICATE_REQUEST_ID")
                        continue
                    if episode_key in finalized:
                        record = ledger.reject(message, "REQUEST_AFTER_FINAL")
                    else:
                        def execute(request: Mapping[str, Any], episode: str = episode_key) -> Mapping[str, Any]:
                            if experiment_executor is None:
                                return {"status": "UNAVAILABLE", "observation": {"status": "executor-not-supplied"}}
                            return dict(experiment_executor(episode, request))
                        record = ledger.run(message, execute)
                    observation = record.get("response", {}).get("observation", {"status": record.get("response", {}).get("status", "UNAVAILABLE")})
                    response = record.get("response", {})
                    error_codes = record.get("error_codes", [])
                    fallback_status = error_codes[0] if error_codes else "UNAVAILABLE"
                    status = response.get("status", fallback_status)
                    result = {"schema_version": V12_PROTOCOL_VERSION, "message": "experiment_result", "episode_id": episode_key, "request_id": request_id, "status": status, "observation": observation}
                    if process.stdin is None:
                        errors.append("CANDIDATE_PROCESS_STDIN_UNAVAILABLE")
                        break
                    process.stdin.write((json.dumps(result, sort_keys=True) + "\n").encode("utf-8"))
                    process.stdin.flush()
                else:
                    if str(episode_id) in finals:
                        errors.append("DUPLICATE_TERMINAL_RESULT")
                        continue
                    finals[str(episode_id)] = cast(dict[str, Any], message["prediction"])
                    finalized.add(str(episode_id))
            if len(finals) != len(packet_list):
                errors.append("MISSING_TERMINAL_RESULT")
            if partial_frame.is_set():
                errors.append("CANDIDATE_PARTIAL_JSONL_FRAME")
            if ended and process.poll() is None:
                errors.append("CANDIDATE_PROTOCOL_EOF")
            if time.monotonic() >= deadline and len(finals) < len(packet_list):
                errors.append("CANDIDATE_TIMEOUT")
            if len(finals) == len(packet_list) and process.poll() is None:
                try:
                    if process.stdin is not None:
                        process.stdin.close()
                    process.wait(timeout=2)
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                    errors.append("CANDIDATE_PROCESS_DID_NOT_EXIT_AFTER_FINAL")
            if process.returncode not in (None, 0):
                errors.append("CANDIDATE_NONZERO_EXIT")
        except (BrokenPipeError, OSError):
            errors.append("CANDIDATE_PROCESS_IO_ERROR")
        finally:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
            try:
                if not self._cleanup_container():
                    errors.append("CANDIDATE_CONTAINER_CLEANUP_FAILED")
            except (OSError, subprocess.SubprocessError):
                errors.append("CANDIDATE_CONTAINER_CLEANUP_FAILED")
        return {"status": "COMPLETED" if not errors and len(finals) == len(packet_list) else "BLOCKED", "network_denied": True, "predictions": finals, "ledgers": {key: value.summary() for key, value in ledgers.items()}, "errors": errors, "exit_code": process.returncode}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return cast(dict[str, Any], value)


def candidate_bundle_audit(root: Path) -> dict[str, Any]:
    path = root / V12_CANDIDATE_BUNDLE_RELATIVE
    if not path.is_file():
        return {"valid": False, "errors": ["candidate bundle is absent"]}
    try:
        document = _read_json(path)
    except (OSError, ValueError) as exc:
        return {"valid": False, "errors": [f"candidate bundle unreadable: {type(exc).__name__}"]}
    errors = validate_candidate_document(document)
    shape = metadata_shape_classifier_audit(document)
    errors.extend(shape["errors"])
    return {"valid": not errors, "errors": errors, "shape_audit": shape, "digest": canonical_digest(document)}


def evaluator_bundle_audit(root: Path, bundle_path: Path | None = None) -> dict[str, Any]:
    path = (bundle_path or (root / V12_EVALUATOR_BUNDLE_RELATIVE)).resolve()
    if not path.is_file():
        return {"valid": False, "errors": ["evaluator bundle is absent"]}
    try:
        document = _read_json(path)
    except (OSError, ValueError) as exc:
        return {"valid": False, "errors": [f"evaluator bundle unreadable: {type(exc).__name__}"]}
    errors: list[str] = []
    if set(document) != {"schema_version", "suite_id", "bundle_type", "record_case_mapping", "labels", "gold_provenance"}:
        errors.append("evaluator bundle fields are not strict")
    if document.get("schema_version") != "1.2" or document.get("suite_id") != V12_SUITE_ID or document.get("bundle_type") != "evaluator-only":
        errors.append("evaluator bundle identity is invalid")
    labels = document.get("labels")
    errors.extend(validate_label_document(labels if isinstance(labels, Mapping) else {}))
    record_case_mapping = document.get("record_case_mapping")
    if not isinstance(record_case_mapping, Mapping):
        errors.append("evaluator record-to-case mapping is absent")
    else:
        errors.extend(validate_record_case_mapping(record_case_mapping))
    provenance = document.get("gold_provenance")
    errors.extend(validate_gold_provenance(provenance if isinstance(provenance, (Mapping, list)) else {}, root))
    return {"valid": not errors, "errors": errors, "digest": file_digest(path)}


def _validate_solvability_reference(root: Path, candidate: Mapping[str, Any], evidence: Mapping[str, Any]) -> list[str]:
    """Recompute the candidate-only gate from raw receipts, never from a status claim."""

    errors: list[str] = []
    if evidence.get("review_type") != "candidate-only-reference":
        errors.append("review type is not candidate-only")
    predictions = evidence.get("raw_predictions")
    receipts = evidence.get("receipts")
    if not isinstance(predictions, list) or len(predictions) != len(HISTORICAL_IDS):
        errors.append("raw candidate-only predictions must contain exactly five records")
    if not isinstance(receipts, list) or len(receipts) != len(HISTORICAL_IDS):
        errors.append("candidate-only receipts must contain exactly five records")
    if evidence.get("evaluator_available_during_run") is not False:
        errors.append("evaluator availability must be false during the candidate run")
    sandbox = evidence.get("sandbox_receipt")
    if not isinstance(sandbox, Mapping):
        errors.append("candidate-only sandbox receipt is absent")
    else:
        for key in ("docker_isolated", "network_denied", "actual_config_verified"):
            if sandbox.get(key) is not True:
                errors.append(f"candidate-only sandbox receipt does not prove {key}")
        count_keys = (
            "declared_mount_count",
            "repository_mount_count",
            "evaluator_mount_count",
            "reference_mount_count",
        )
        valid_counts: dict[str, int] = {}
        for key in count_keys:
            value = sandbox.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"candidate-only sandbox receipt has an invalid {key}")
            else:
                valid_counts[key] = value
        if len(valid_counts) == len(count_keys):
            if any(
                valid_counts[key] != 0
                for key in count_keys
            ):
                errors.append("candidate-only sandbox must have no host, repository, evaluator, or reference mounts")
            if evidence.get("evaluator_available_during_run") is not (valid_counts["evaluator_mount_count"] > 0):
                errors.append("evaluator availability is not derived from the sandbox receipt")
    expected_digest = candidate.get("digest")
    if not isinstance(expected_digest, str) or evidence.get("candidate_bundle_digest") != expected_digest:
        errors.append("solvability reference is not bound to the candidate bundle digest")
    if isinstance(predictions, list):
        seen: set[str] = set()
        for item in predictions:
            if not isinstance(item, Mapping):
                errors.append("raw prediction is not an object")
                continue
            episode_id = item.get("episode_id")
            if not isinstance(episode_id, str) or episode_id in seen:
                errors.append("raw prediction episode IDs must be unique opaque strings")
            seen.add(str(episode_id))
            if item.get("disposition") not in DISPOSITIONS:
                errors.append("raw prediction disposition is invalid")
            if item.get("semantic_intent") not in SEMANTIC_INTENTS:
                errors.append("raw prediction semantic intent is invalid")
            if item.get("causal_component") is not None and not isinstance(item.get("causal_component"), str):
                errors.append("raw prediction causal component is invalid")
            if not isinstance(item.get("candidate_induced"), bool):
                errors.append("raw prediction candidate-induced field is invalid")
            if not isinstance(item.get("evidence_digest"), str) or not HEX64.fullmatch(str(item.get("evidence_digest")).removeprefix("sha256:")):
                errors.append("raw prediction evidence digest is invalid")
            if "case_id" in item or "gold" in item or "label" in item:
                errors.append("raw candidate-only prediction contains evaluator identity")
    if isinstance(receipts, list):
        for item in receipts:
            if (
                not isinstance(item, Mapping)
                or item.get("status") != "COMPLETED"
                or not isinstance(item.get("receipt_digest"), str)
                or not HEX64.fullmatch(str(item.get("receipt_digest")).removeprefix("sha256:"))
                or item.get("fresh") is not True
                or item.get("available") is not True
                or item.get("cleanup_verified") is not True
                or not isinstance(item.get("experiment_count"), int)
                or isinstance(item.get("experiment_count"), bool)
                or cast(int, item.get("experiment_count")) != 1
            ):
                errors.append("candidate-only experiment receipt is invalid")
    review = evidence.get("historical_review")
    if not isinstance(review, list) or len(review) != len(HISTORICAL_IDS):
        errors.append("historical review must contain five opaque episode assertions")
    else:
        by_episode = {str(item.get("episode_id")): item for item in predictions if isinstance(item, Mapping) and isinstance(item.get("episode_id"), str)} if isinstance(predictions, list) else {}
        roles = {str(item.get("role")) for item in review if isinstance(item, Mapping)}
        if roles != {"A01_OR_OTHER", "A02_SCIPY", "A03_AMBIGUOUS", "A04_OR_OTHER", "A05_OR_OTHER"}:
            errors.append("historical review roles do not cover the preregistered cross-repository and semantic gates")
        passed = 0
        for item in review:
            if not isinstance(item, Mapping) or not isinstance(item.get("episode_id"), str):
                errors.append("historical review assertion is invalid")
                continue
            prediction = by_episode.get(str(item["episode_id"]))
            if not isinstance(prediction, Mapping):
                errors.append("historical review references an unknown episode")
                continue
            role = item.get("role")
            expected = SUFFICIENCY_ROLE_EXPECTATIONS.get(str(role))
            if expected is None:
                errors.append(f"historical review role is not preregistered: {role}")
                continue
            expected_disposition, expected_semantic_intent, expected_component = expected
            matches = (
                prediction.get("disposition") == expected_disposition
                and prediction.get("semantic_intent") == expected_semantic_intent
                and prediction.get("causal_component") == expected_component
            )
            passed += int(matches)
            if not matches:
                errors.append(
                    f"{role} does not match the exact preregistered disposition, semantic intent, and causal component"
                )
        if passed < 4:
            errors.append("raw candidate-only predictions do not meet the four-of-five historical disposition gate")
    metadata = evidence.get("metadata_only")
    if not isinstance(metadata, Mapping) or metadata.get("case_type_signal") not in {"NONE", "NO_SIGNAL"}:
        errors.append("metadata-only lane has not demonstrated no case-type signal")
    elif not isinstance(metadata.get("classifier_advantage"), (int, float)) or not 0 <= float(metadata["classifier_advantage"]) <= 0.2:
        errors.append("metadata-only lane exceeds the preregistered predictive bound")
    return errors


def information_sufficiency_audit(root: Path) -> dict[str, Any]:
    """Candidate-only sufficiency gate; bundle validity is never solvability."""

    candidate = candidate_bundle_audit(root)
    reference_path = root / V12_SOLVABILITY_RELATIVE
    evidence: dict[str, Any] | None = None
    errors: list[str] = []
    if reference_path.is_file():
        try:
            evidence = _read_json(reference_path)
            errors.extend(_validate_solvability_reference(root, candidate, evidence))
        except (OSError, ValueError) as exc:
            errors.append(f"candidate-only solvability reference unreadable: {type(exc).__name__}")
    else:
        errors.append("no blinded candidate-only solvability reference exists")
    status = "PASS" if candidate["valid"] and evidence is not None and not errors else "BLOCKED_INFORMATION_SUFFICIENCY"
    sandbox = evidence.get("sandbox_receipt") if isinstance(evidence, Mapping) else None
    evaluator_mount_count = sandbox.get("evaluator_mount_count") if isinstance(sandbox, Mapping) else None
    evaluator_loaded = (
        isinstance(evaluator_mount_count, int)
        and not isinstance(evaluator_mount_count, bool)
        and evaluator_mount_count > 0
    )
    return {
        "status": status,
        "candidate_bundle": candidate,
        "solvability_reference": {"path": str(V12_SOLVABILITY_RELATIVE), "present": reference_path.is_file(), "errors": errors},
        "preregistered_gates": {
            "historical_causal_or_semantic_disposition": ">=4/5",
            "scikit_learn_30512_component": "SciPy",
            "pandas_45601": "semantic ambiguity must remain unresolved if unsupported",
            "safety_case_type_inference": "must not be inferable from IDs, order, or evidence shape",
        },
        "evaluator_loaded": evaluator_loaded,
        "certifying": False if status != "PASS" else bool(evidence and evidence.get("certifying")),
    }


def _runtime_audit(root: Path) -> dict[str, Any]:
    path = root / V12_SUITE_RELATIVE.parent / "runtime-recipes.json"
    if not path.is_file():
        return {"status": "BLOCKED", "errors": ["HISTORICAL_RUNTIME_RECONSTRUCTION"]}
    try:
        document = _read_json(path)
    except (OSError, ValueError) as exc:
        return {"status": "BLOCKED", "errors": [f"runtime recipes unreadable: {type(exc).__name__}"]}
    recipes = document.get("recipes")
    errors: list[str] = []
    if document.get("suite_id") != V12_SUITE_ID or not isinstance(recipes, list) or len(recipes) != 5:
        errors.append("runtime recipe identity or count is invalid")
    for recipe in recipes if isinstance(recipes, list) else []:
        if not isinstance(recipe, Mapping):
            errors.append("runtime recipe is not an object")
            continue
        platform = recipe.get("platform")
        image = platform.get("container_image") if isinstance(platform, Mapping) else None
        if not isinstance(image, str) or not IMAGE_DIGEST.fullmatch(image):
            errors.append(f"{recipe.get('case_id')}: full digest-pinned base image is required")
        reproducer = recipe.get("reproducer")
        reproducer_digest = recipe.get("reproducer_sha256")
        reproducer_path = root / str(reproducer) if isinstance(reproducer, str) else None
        if reproducer_path is None or not reproducer_path.is_file() or not isinstance(reproducer_digest, str) or not reproducer_digest.startswith("sha256:") or file_digest(reproducer_path) != reproducer_digest:
            errors.append(f"{recipe.get('case_id')}: reproducer existence or digest is invalid")
        for side in ("control", "candidate"):
            value = recipe.get(side)
            if not isinstance(value, Mapping) or not isinstance(value.get("packages"), list) or not value.get("packages") or not isinstance(value.get("command"), list) or not value.get("command"):
                errors.append(f"{recipe.get('case_id')}: {side} runtime is incomplete")
    return {"status": "READY" if not errors else "BLOCKED", "errors": errors, "recipe_digest": file_digest(path)}


def evaluate_v12(root: Path, *, candidate_image: str | None = None, candidate_argv: Sequence[str] | None = None, evaluator_bundle_path: Path | None = None, artifact_root: Path | None = None, candidate_command: Sequence[str] | str | None = None) -> dict[str, Any]:
    """Evaluate only after candidate-only sufficiency and runtime gates pass."""

    candidate_audit = candidate_bundle_audit(root)
    runtime_audit = _runtime_audit(root)
    result: dict[str, Any] = {"schema_version": V12_PROTOCOL_VERSION, "suite_id": V12_SUITE_ID, "release_version": V12_RELEASE_VERSION, "status": "BLOCKED", "candidate_gold_visible": False, "candidate_repository_visible": False, "network_used": False, "episode_ids": "evaluator-only-random-per-run", "candidate_bundle": candidate_audit, "runtime": runtime_audit, "artifact_root": "external-artifact-root" if artifact_root else None, "blockers": []}
    sufficiency = information_sufficiency_audit(root)
    result["information_sufficiency"] = sufficiency
    if sufficiency["status"] != "PASS":
        result["blockers"].append("BLOCKED_INFORMATION_SUFFICIENCY")
        return result
    if runtime_audit["status"] != "READY":
        result["blockers"].append("BLOCKED_REPRODUCIBILITY")
    artifact_catalog = root / V12_SUITE_RELATIVE.parent / "artifact-catalog.json"
    baseline_audit = baseline_freeze_audit(root)
    if not artifact_catalog.is_file():
        result["blockers"].append("BLOCKED_ARTIFACT_CATALOG")
    if baseline_audit["status"] != "PASS":
        result["blockers"].append("BLOCKED_BASELINE_PROVENANCE")
    if candidate_image is None or candidate_argv is None:
        if candidate_command is not None:
            result["blockers"].append("CANDIDATE_COMMAND_DEPRECATED_USE_IMAGE_AND_ARGV")
        else:
            result["blockers"].append("CANDIDATE_IMAGE_AND_ARGV_REQUIRED")
    evaluator_audit = evaluator_bundle_audit(root, evaluator_bundle_path)
    result["evaluator_bundle"] = evaluator_audit
    if not evaluator_audit["valid"]:
        result["blockers"].append("BLOCKED_BENCHMARK_INTEGRITY")
    if result["blockers"]:
        return result
    candidate_document = _read_json(root / V12_CANDIDATE_BUNDLE_RELATIVE)
    evaluator_document = _read_json(evaluator_bundle_path or root / V12_EVALUATOR_BUNDLE_RELATIVE)
    record_case_mapping = cast(Mapping[str, Any], evaluator_document["record_case_mapping"])
    mapping = generate_episode_ids(ALL_CASE_IDS)
    packets = build_candidate_packets(candidate_document, record_case_mapping, mapping)
    workspace = root / ".candidate-workspace-v1.2"
    workspace.mkdir(mode=0o700, exist_ok=True)
    try:
        if not isinstance(candidate_image, str) or candidate_argv is None:
            result["blockers"].append("CANDIDATE_IMAGE_AND_ARGV_REQUIRED")
            return result
        protocol = ExternalCandidateProtocol(candidate_image, candidate_argv, working_directory=workspace)
        from radar_bench.v12_executor import V12ExperimentExecutor

        inverse = {episode: case for case, episode in mapping.items()}
        executor = V12ExperimentExecutor(root, episode_to_case=inverse, artifact_root=artifact_root)
        protocol_result = protocol.run(packets, experiment_executor=executor)
    finally:
        try:
            workspace.rmdir()
        except OSError:
            pass
    result["protocol"] = {"version": V12_PROTOCOL_VERSION, "docker_isolated": protocol.docker_isolated, "network_denied": protocol_result.get("network_denied", False)}
    result["protocol_result"] = {key: value for key, value in protocol_result.items() if key not in {"predictions", "ledgers"}}
    if protocol_result.get("status") != "COMPLETED":
        result["blockers"].append("BLOCKED_CANDIDATE_OUTPUT")
        return result
    inverse = {episode: case for case, episode in mapping.items()}
    predictions = cast(Mapping[str, Mapping[str, Any]], protocol_result["predictions"])
    runs: dict[str, Mapping[str, Any]] = {}
    for episode, prediction in predictions.items():
        runs[inverse[episode]] = {"prediction": prediction, "ledger": protocol_result.get("ledgers", {}).get(episode, {})}
    labels = cast(Mapping[str, Mapping[str, Any]], cast(Mapping[str, Any], evaluator_document["labels"])["cases"])
    result["runs"] = runs
    result["episode_count"] = len(predictions)
    result["mapping_digest"] = canonical_digest(sorted(mapping.items()))
    result["metrics"] = score_v12(labels, runs)["metrics"]
    ledgers = cast(Mapping[str, Mapping[str, Any]], protocol_result.get("ledgers", {}))
    case_receipts = {inverse[episode]: receipt for episode, receipt in ledgers.items() if episode in inverse}
    result["candidate_bundle_digest"] = candidate_audit.get("digest")
    result["evaluator_bundle_digest"] = evaluator_audit.get("digest")
    result["runtime_digest"] = runtime_audit.get("recipe_digest")
    result["artifact_catalog_digest"] = file_digest(artifact_catalog)
    result["baseline_digests"] = {"baseline-freeze-v1.2": baseline_audit.get("manifest_digest")}
    result["protocol_version"] = V12_PROTOCOL_VERSION
    result["executor_capability_version"] = "radar-v12-executor-receipt-1"
    result["platform_contract"] = {"os": "linux", "architecture": "x86_64", "runtime": "docker", "network": "none"}
    cleanup_errors = list(cast(Sequence[str], protocol_result.get("errors", [])))
    experiment_cleanup_verified = all(
        int(receipt.get("cleanup_verified", 0)) == int(receipt.get("executor_calls", 0))
        for receipt in ledgers.values()
    )
    cleanup_verified = not cleanup_errors and experiment_cleanup_verified
    result["isolation_verification"] = {"candidate_gold_hidden": True, "candidate_repository_hidden": True, "network_denied": bool(protocol_result.get("network_denied")), "cleanup_verified": cleanup_verified}
    result["experiment_receipts"] = case_receipts
    result["predictions"] = {inverse[episode]: prediction for episode, prediction in predictions.items() if episode in inverse}
    result["source_provenance"] = {
        "suite": file_digest(root / V12_SUITE_RELATIVE),
        "candidate_bundle": result["candidate_bundle_digest"],
        "evaluator_bundle": result["evaluator_bundle_digest"],
        "runtime": result["runtime_digest"],
        "artifact_catalog": result["artifact_catalog_digest"],
        "baseline": baseline_audit.get("manifest_digest"),
    }
    result["cleanup_status"] = {
        "candidate_container": "VERIFIED" if not any(error == "CANDIDATE_CONTAINER_CLEANUP_FAILED" for error in cleanup_errors) else "FAILED",
        "experiment_containers": "VERIFIED" if experiment_cleanup_verified else "FAILED",
        "preparation_volumes": "VERIFIED" if experiment_cleanup_verified else "FAILED",
        "errors": cleanup_errors,
    }
    result["decision"] = "COMPLETED"
    result["scientific_classification"] = "SCIENTIFICALLY_EVALUABLE"
    result["status"] = "COMPLETED"
    return result


def secure_temp_workspace(prefix: str = "radar-v12-") -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix=prefix)


def build_file_manifest(root: Path, paths: Iterable[Path]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in sorted((item.resolve() for item in paths), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"baseline source is not a regular file: {path}")
        records.append({"path": path.relative_to(root.resolve()).as_posix(), "bytes": path.stat().st_size, "sha256": file_digest(path)})
    return {"files": records, "tree_digest": canonical_digest(records)}


def validate_file_manifest(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    records = manifest.get("files")
    if not isinstance(records, list):
        return {"valid": False, "errors": ["file manifest files must be a list"]}
    observed: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            errors.append("invalid file manifest record")
            continue
        path = (root / str(item["path"])).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            errors.append(f"manifest path escapes root: {item['path']}")
            continue
        if not path.is_file() or path.is_symlink():
            errors.append(f"manifest file absent: {item['path']}")
            continue
        actual = {"path": str(item["path"]), "bytes": path.stat().st_size, "sha256": file_digest(path)}
        observed.append(actual)
        if actual["bytes"] != item.get("bytes") or actual["sha256"] != item.get("sha256"):
            errors.append(f"manifest digest mismatch: {item['path']}")
    if manifest.get("tree_digest") != canonical_digest(observed):
        errors.append("manifest tree digest mismatch")
    return {"valid": not errors, "errors": errors}


def baseline_freeze_audit(root: Path) -> dict[str, Any]:
    path = root / "corpus/v1.1.0/decisive-v1.2/baseline-freeze-v1.2.json"
    if not path.is_file():
        return {"status": "BLOCKED", "errors": ["baseline freeze manifest is absent"]}
    try:
        document = _read_json(path)
    except (OSError, ValueError) as exc:
        return {"status": "BLOCKED", "errors": [f"baseline freeze unreadable: {type(exc).__name__}"]}
    errors: list[str] = []
    observed: dict[str, Any] = {}
    for name, entry in (document.get("baselines") or {}).items():
        if name == "agentic-v0.5-frozen" and isinstance(entry, Mapping) and isinstance(entry.get("git_source_manifest"), Mapping):
            source_manifest = cast(Mapping[str, Any], entry["git_source_manifest"])
            source_records: list[dict[str, Any]] = []
            commit = str(entry.get("originating_commit", ""))
            for raw in source_manifest.get("files", []):
                if not isinstance(raw, Mapping) or not isinstance(raw.get("path"), str):
                    errors.append(f"{name}: invalid Git source record")
                    continue
                completed = subprocess.run(  # nosec B603, B607 - fixed git argv and shell disabled
                    ["git", "-C", str(root), "show", f"{commit}:{raw['path']}"],
                    capture_output=True,
                    check=False,
                    shell=False,
                )
                payload = completed.stdout
                record = {"path": str(raw["path"]), "bytes": len(payload), "sha256": "sha256:" + hashlib.sha256(payload).hexdigest()}
                source_records.append(record)
                if completed.returncode != 0 or record["bytes"] != raw.get("bytes") or record["sha256"] != raw.get("sha256"):
                    errors.append(f"{name}: Git source digest mismatch: {raw['path']}")
            if canonical_digest(source_records) != source_manifest.get("canonical_tree_digest"):
                errors.append(f"{name}: Git source tree digest mismatch")
            adapter = entry.get("compatibility_adapter")
            if not isinstance(adapter, Mapping) or adapter.get("status") != "PORT_NOT_BYTE_IDENTICAL":
                errors.append(f"{name}: compatibility adapter must be separately labelled")
            observed[str(name)] = {"git_source_files": source_records, "canonical_tree_digest": canonical_digest(source_records), "compatibility_adapter": adapter}
            continue
        if not isinstance(entry, Mapping) or not isinstance(entry.get("files"), list):
            errors.append(f"{name}: invalid source manifest")
            continue
        records: list[dict[str, Any]] = []
        for raw in entry["files"]:
            if not isinstance(raw, Mapping) or not isinstance(raw.get("path"), str):
                errors.append(f"{name}: invalid source record")
                continue
            file_path = root / str(raw["path"])
            if not file_path.is_file() or file_path.is_symlink():
                errors.append(f"{name}: source is absent: {raw['path']}")
                continue
            record = {"path": str(raw["path"]), "bytes": file_path.stat().st_size, "sha256": file_digest(file_path)}
            records.append(record)
            if record["bytes"] != raw.get("bytes") or record["sha256"] != raw.get("sha256"):
                errors.append(f"{name}: source digest mismatch: {raw['path']}")
        tree_digest = canonical_digest(records)
        if tree_digest != entry.get("canonical_tree_digest"):
            errors.append(f"{name}: canonical tree digest mismatch")
        observed[str(name)] = {"files": records, "canonical_tree_digest": tree_digest}
    return {"status": "PASS" if not errors else "BLOCKED", "errors": errors, "observed": observed, "manifest_digest": file_digest(path)}


def exact_reference_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("suite_digest", "candidate_bundle_digest", "evaluator_bundle_digest", "safety_digest", "runtime_digest", "baseline_digest", "executor_capability_version", "candidate_protocol", "platform", "decision", "metrics", "predictions")
    return {key: result.get(key) for key in keys}


def compare_exact_reference(result: Mapping[str, Any], reference: Mapping[str, Any] | None) -> dict[str, Any]:
    if reference is None:
        return {"status": "NO_REFERENCE"}
    current = exact_reference_projection(result)
    expected = exact_reference_projection(reference)
    return {"status": "EXACT_MATCH" if current == expected else "DRIFT", "scores_equal": current.get("metrics") == expected.get("metrics"), "inputs_equal": current == expected, "current_digest": canonical_digest(current), "reference_digest": canonical_digest(expected)}


def separation_audit(root: Path) -> dict[str, Any]:
    candidate = root / V12_CANDIDATE_BUNDLE_RELATIVE
    evaluator = root / V12_EVALUATOR_BUNDLE_RELATIVE
    errors: list[str] = []
    if not candidate.is_file():
        errors.append("candidate bundle absent")
    if not evaluator.is_file():
        errors.append("evaluator bundle absent")
    if candidate.is_file():
        text = candidate.read_text(encoding="utf-8").lower()
        if any(token in text for token in ("gold_evidence", "gold_provenance", "action_owner_repository", "evaluator-labels")):
            errors.append("candidate bundle contains evaluator-only content")
    return {"valid": not errors, "errors": errors, "candidate_digest": file_digest(candidate) if candidate.is_file() else None, "evaluator_digest": file_digest(evaluator) if evaluator.is_file() else None}


def source_package_mirror_audit(root: Path) -> dict[str, Any]:
    pairs = (
        (root / "candidate/decisive-v1.2/candidate-bundle.json", root / "src/radar_bench/resources/candidate/decisive-v1.2/candidate-bundle.json"),
        (root / "corpus/v1.1.0/decisive-v1.2/suite.json", root / "src/radar_bench/resources/corpus/v1.1.0/decisive-v1.2/suite.json"),
        (root / "corpus/v1.1.0/decisive-v1.2/artifact-catalog.json", root / "src/radar_bench/resources/corpus/v1.1.0/decisive-v1.2/artifact-catalog.json"),
        (root / "corpus/v1.1.0/decisive-v1.2/runtime-recipes.json", root / "src/radar_bench/resources/corpus/v1.1.0/decisive-v1.2/runtime-recipes.json"),
        (root / "corpus/v1.1.0/decisive-v1.2/metric-contract-v1.2.json", root / "src/radar_bench/resources/corpus/v1.1.0/decisive-v1.2/metric-contract-v1.2.json"),
    )
    mismatches: list[str] = []
    for source, packaged in pairs:
        if not source.is_file() or not packaged.is_file():
            mismatches.append(f"missing mirror: {source.name}")
            continue
        try:
            if canonical_digest(_read_json(source)) != canonical_digest(_read_json(packaged)):
                mismatches.append(f"digest mismatch: {source.name}")
        except (OSError, ValueError):
            mismatches.append(f"digest mismatch: {source.name}")
    return {"status": "PASS" if not mismatches else "FAIL", "mismatches": mismatches, "pair_count": len(pairs)}
