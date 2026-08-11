"""Case-agnostic v1.2 evaluation primitives.

The v1.1 corpus is immutable historical evidence.  This module is deliberately
additive: it supplies the corrected v1.2 protocol, separation checks, scoring
contracts, and provenance helpers without changing the old evaluator or its
reference result.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shlex
import subprocess  # nosec B404 - argv is supplied as a validated array and shell is disabled
import tempfile
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

HISTORICAL_IDS = tuple(f"RADAR-V07-A{index:02d}" for index in range(1, 6))
SAFETY_IDS = tuple(f"RADAR-V07-T{index:02d}" for index in range(1, 21))
ALL_CASE_IDS = HISTORICAL_IDS + SAFETY_IDS

CAPABILITIES = frozenset(
    {
        "rerun",
        "change_dependency_version",
        "freeze_dependency",
        "bisect_component",
        "toggle_environment_variable",
        "run_minimal_test",
        "inspect_dependency_graph",
    }
)
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
    }
)
FORBIDDEN_CANDIDATE_TOKENS = ("evaluator-labels", "reference/", "gold/")


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
    """Create fresh evaluator-only IDs; no public case ID is encoded in them."""

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
    """Canonicalize evaluator output without trusting candidate order."""

    return sorted(results, key=lambda item: str(item.get("episode_id", "")))


def validate_experiment_request(request: Mapping[str, Any]) -> list[str]:
    """Validate capability and parameters before consulting any case lookup."""

    errors: list[str] = []
    capability = request.get("capability")
    if capability not in CAPABILITIES:
        errors.append("UNSUPPORTED_CAPABILITY")
        return errors
    parameters = request.get("parameters", {})
    if not isinstance(parameters, Mapping):
        return ["PARAMETERS_NOT_OBJECT"]
    required: dict[str, tuple[str, ...]] = {
        "rerun": (),
        "change_dependency_version": ("target_component", "version"),
        "freeze_dependency": ("target_component",),
        "bisect_component": ("component",),
        "toggle_environment_variable": ("name", "value"),
        "run_minimal_test": ("command",),
        "inspect_dependency_graph": (),
    }
    for name in required[str(capability)]:
        if not isinstance(parameters.get(name), (str, int, float, bool)):
            errors.append(f"MISSING_PARAMETER:{name}")
    if "command" in parameters and not isinstance(parameters["command"], (str, list, tuple)):
        errors.append("INVALID_PARAMETER:command")
    return errors


@dataclass
class ExperimentLedger:
    """Account for each request; reruns are always fresh and never cached."""

    attempts: list[dict[str, Any]] = field(default_factory=list)

    def run(
        self,
        request: Mapping[str, Any],
        executor: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> dict[str, Any]:
        errors = validate_experiment_request(request)
        record: dict[str, Any] = {
            "capability": request.get("capability"),
            "requested": True,
            "valid": not errors,
            "fresh": False,
            "cache_hit": False,
            "reused": False,
            "available": False,
            "useful": False,
            "error_codes": errors,
        }
        if errors:
            self.attempts.append(record)
            return record
        started = time.monotonic()
        try:
            response = dict(executor(dict(request)))
        except Exception as exc:  # pragma: no cover - defensive provider boundary
            response = {"status": "EXECUTION_ERROR", "error_codes": [type(exc).__name__]}
        record["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
        record["response"] = response
        record["available"] = response.get("status") not in {
            "UNSUPPORTED_EXPERIMENT",
            "INVALID_REQUEST",
            "EXECUTION_ERROR",
        }
        record["fresh"] = bool(record["available"])
        record["cache_hit"] = False
        record["reused"] = False
        result = response.get("result")
        record["useful"] = bool(
            record["available"] and isinstance(result, Mapping) and result.get("useful")
        )
        self.attempts.append(record)
        return record

    def summary(self) -> dict[str, Any]:
        requested = len(self.attempts)
        valid = sum(int(item["valid"]) for item in self.attempts)
        fresh = sum(int(item["fresh"]) for item in self.attempts)
        useful = sum(int(item["useful"]) for item in self.attempts)
        return {
            "requested": requested,
            "valid": valid,
            "fresh": fresh,
            "cache_hits": sum(int(item["cache_hit"]) for item in self.attempts),
            "reused": sum(int(item["reused"]) for item in self.attempts),
            "available": sum(int(item["available"]) for item in self.attempts),
            "useful_fresh": useful,
            "fresh_useful_experiment_rate": _metric(useful, fresh),
            "requested_experiment_efficiency": _metric(fresh, requested),
        }


def validate_candidate_document(document: Mapping[str, Any]) -> list[str]:
    """Reject evaluator-only content from candidate-visible JSON."""

    errors: list[str] = []

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
        elif isinstance(value, str):
            lowered = value.lower()
            for token in FORBIDDEN_CANDIDATE_TOKENS:
                if token in lowered:
                    errors.append(f"evaluator-only path token: {path}")

    visit(document)
    return errors


def validate_label_case(case_id: str, label: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = label.get("expected_terminal_state")
    if expected not in {"CAUSALLY_ATTRIBUTED", "SEMANTICALLY_AMBIGUOUS", "ABSTAINED"}:
        errors.append(f"{case_id}: invalid expected_terminal_state")
    for key in ("candidate_induced", "root_cause_scored", "action_owner_scored"):
        if not isinstance(label.get(key), bool):
            errors.append(f"{case_id}: {key} must be boolean")
    if label.get("root_cause_scored") and not label.get("root_cause_component"):
        errors.append(f"{case_id}: root cause score requires a component")
    if label.get("action_owner_scored") and not label.get("action_owner_repository"):
        errors.append(f"{case_id}: action owner score requires a repository")
    if expected == "SEMANTICALLY_AMBIGUOUS" and label.get("action_owner_scored"):
        errors.append(f"{case_id}: semantic ambiguity cannot score action owner")
    if not isinstance(label.get("scoring_eligibility_rationale"), str) or not label.get(
        "scoring_eligibility_rationale"
    ):
        errors.append(f"{case_id}: scoring rationale is required")
    if not isinstance(label.get("gold_evidence_ids"), list) or not label.get("gold_evidence_ids"):
        errors.append(f"{case_id}: gold evidence IDs are required")
    return errors


def validate_label_document(document: Mapping[str, Any]) -> list[str]:
    if document.get("schema_version") != "1.2":
        return ["label document has the wrong schema version"]
    cases = document.get("cases")
    if not isinstance(cases, Mapping):
        return ["label document cases must be an object"]
    errors = [error for case_id, label in cases.items() if isinstance(label, Mapping) for error in validate_label_case(str(case_id), label)]
    missing = set(ALL_CASE_IDS) - set(str(case_id) for case_id in cases)
    if missing:
        errors.append("label document is missing cases: " + ",".join(sorted(missing)))
    return errors


def _prediction_claim(run: Mapping[str, Any]) -> bool:
    terminal = run.get("terminal")
    return isinstance(terminal, Mapping) and terminal.get("state") == "CAUSALLY_ATTRIBUTED"


def _run_attempts(run: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    attempts = run.get("attempts", [])
    return [item for item in attempts if isinstance(item, Mapping)] if isinstance(attempts, list) else []


def score_v12(labels: Mapping[str, Mapping[str, Any]], runs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Score corrected labels only after candidate runs have completed."""

    errors = validate_label_document({"schema_version": "1.2", "cases": labels})
    if errors:
        raise ValueError("invalid v1.2 labels: " + "; ".join(errors))
    metrics = empty_v12_metrics()
    historical_resolution = historical_abstention = semantic = induced = root = owner = cross = 0
    owner_denominator = 0
    safety_abstention = premature = 0
    useful = fresh = requested = 0
    for case_id in HISTORICAL_IDS:
        label = labels[case_id]
        run = runs.get(case_id, {})
        terminal = run.get("terminal", {})
        if not isinstance(terminal, Mapping):
            terminal = {}
        claim = _prediction_claim(run)
        expected = label["expected_terminal_state"]
        if expected == "SEMANTICALLY_AMBIGUOUS":
            semantic += int(terminal.get("state") == "SEMANTICALLY_AMBIGUOUS" or not claim)
            historical_resolution += int(not claim)
        elif expected == "ABSTAINED":
            historical_abstention += int(not claim)
        else:
            historical_resolution += int(claim)
        induced += int(terminal.get("candidate_induced") == label["candidate_induced"])
        if label["root_cause_scored"]:
            root += int(claim and terminal.get("root_cause_component") == label.get("root_cause_component"))
        if label["action_owner_scored"]:
            owner_denominator += 1
            owner += int(claim and terminal.get("action_owner_repository") == label.get("action_owner_repository"))
        if case_id == "RADAR-V07-A02":
            cross += int(claim and terminal.get("root_cause_component") == "https://github.com/scipy/scipy")
        for attempt in _run_attempts(run):
            requested += int(attempt.get("requested", True))
            fresh += int(attempt.get("fresh", False))
            useful += int(attempt.get("useful", False) and attempt.get("fresh", False))
    for case_id in SAFETY_IDS:
        run = runs.get(case_id, {})
        claim = _prediction_claim(run)
        safety_abstention += int(not claim)
        premature += int(claim)
        for attempt in _run_attempts(run):
            requested += int(attempt.get("requested", True))
            fresh += int(attempt.get("fresh", False))
            useful += int(attempt.get("useful", False) and attempt.get("fresh", False))
    metrics.update(
        {
            "historical_attribution_resolution": _metric(historical_resolution, 5),
            "historical_correct_abstention": _metric(historical_abstention, 5),
            "semantic_ambiguity_handling": _metric(semantic, 1),
            "candidate_induced_correctness": _metric(induced, 5),
            "root_cause_component_correctness": _metric(root, sum(int(labels[item]["root_cause_scored"]) for item in HISTORICAL_IDS)),
            "action_owner_correctness": _metric(owner, owner_denominator),
            "cross_repository_resolution": _metric(cross, 1),
            "safety_abstention_recall": _metric(safety_abstention, 20),
            "false_owner_accusation_rate": _metric(premature, 20),
            "fresh_useful_experiment_rate": _metric(useful, fresh),
            "requested_experiment_efficiency": _metric(fresh, requested),
        }
    )
    return {"schema_version": V12_PROTOCOL_VERSION, "metrics": metrics}


@dataclass(frozen=True)
class CandidatePacket:
    episode_id: str
    evidence: Mapping[str, Any]
    capabilities: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "schema_version": V12_PROTOCOL_VERSION,
            "message": "episode",
            "episode_id": self.episode_id,
            "candidate_visible_evidence": dict(self.evidence),
            "capabilities": list(self.capabilities),
        }


class ExternalCandidateProtocol:
    """Length-bounded JSONL protocol for an external investigator."""

    def __init__(
        self,
        command: Sequence[str] | str,
        *,
        working_directory: Path,
        timeout_seconds: float = 30.0,
        max_line_bytes: int = 256 * 1024,
    ) -> None:
        self.command = tuple(shlex.split(command, posix=False) if isinstance(command, str) else command)
        self.working_directory = working_directory.resolve()
        self.timeout_seconds = timeout_seconds
        self.max_line_bytes = max_line_bytes
        if not self.command:
            raise ValueError("candidate command is empty")

    @property
    def docker_isolated(self) -> bool:
        lowered = [item.lower() for item in self.command]
        required_flags = {
            "--network": "none",
            "--read-only": None,
            "--cap-drop": "all",
            "--memory": None,
            "--cpus": None,
            "--pids-limit": None,
        }
        if Path(lowered[0]).name not in {"docker", "docker.exe"}:
            return False
        for flag, value in required_flags.items():
            if flag not in lowered:
                return False
            if value is not None:
                index = lowered.index(flag)
                if index + 1 >= len(lowered) or lowered[index + 1] != value:
                    return False
        return True

    def run(self, packets: Iterable[CandidatePacket]) -> dict[str, Any]:
        if not self.working_directory.is_dir():
            return {"status": "BLOCKED", "error": "CANDIDATE_WORKSPACE_ABSENT"}
        if not self.docker_isolated:
            return {
                "status": "BLOCKED",
                "error": "CANDIDATE_ISOLATION_NOT_PROVEN",
                "network_denied": False,
            }
        safe_env = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": "C",
            "LC_ALL": "C",
            "RADAR_BENCH_EXTERNAL_CANDIDATE": "1",
        }
        try:
            process = subprocess.Popen(  # nosec B603 - shell=False with an explicit argv array
                list(self.command),
                cwd=self.working_directory,
                env=safe_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            return {"status": "BLOCKED", "error": "CANDIDATE_PROCESS_UNAVAILABLE", "detail": type(exc).__name__}
        messages = "\n".join(json.dumps(packet.as_json(), sort_keys=True) for packet in packets) + "\n"
        try:
            stdout, stderr = process.communicate(messages, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return {"status": "BLOCKED", "error": "CANDIDATE_TIMEOUT", "network_denied": True}
        if len(stdout.encode("utf-8")) > self.max_line_bytes * 64:
            return {"status": "BLOCKED", "error": "CANDIDATE_OUTPUT_LIMIT", "network_denied": True}
        responses: list[dict[str, Any]] = []
        errors: list[str] = []
        for line in stdout.splitlines():
            if len(line.encode("utf-8")) > self.max_line_bytes:
                errors.append("CANDIDATE_LINE_LIMIT")
                continue
            try:
                value = json.loads(line)
            except ValueError:
                errors.append("CANDIDATE_NON_JSON_OUTPUT")
                continue
            if not isinstance(value, dict):
                errors.append("CANDIDATE_RESPONSE_NOT_OBJECT")
                continue
            responses.append(value)
        if process.returncode != 0:
            errors.append("CANDIDATE_PROCESS_FAILED")
        if stderr:
            errors.append("CANDIDATE_STDERR_PRESENT")
        return {
            "status": "COMPLETED" if not errors else "BLOCKED",
            "network_denied": True,
            "responses": [dict(item) for item in canonicalize_case_order(responses)],
            "errors": errors,
        }


def candidate_bundle_audit(root: Path) -> dict[str, Any]:
    path = root / V12_CANDIDATE_BUNDLE_RELATIVE
    if not path.is_file():
        return {"valid": False, "errors": ["candidate bundle is absent"]}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"valid": False, "errors": [f"candidate bundle unreadable: {type(exc).__name__}"]}
    if not isinstance(document, dict):
        return {"valid": False, "errors": ["candidate bundle must be an object"]}
    errors = validate_candidate_document(document)
    if document.get("suite_id") != V12_SUITE_ID:
        errors.append("candidate bundle suite identity is wrong")
    return {"valid": not errors, "errors": errors, "digest": canonical_digest(document)}


def evaluator_bundle_audit(root: Path) -> dict[str, Any]:
    path = root / V12_EVALUATOR_BUNDLE_RELATIVE
    if not path.is_file():
        return {"valid": False, "errors": ["evaluator bundle is absent"]}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"valid": False, "errors": [f"evaluator bundle unreadable: {type(exc).__name__}"]}
    if not isinstance(document, dict):
        return {"valid": False, "errors": ["evaluator bundle must be an object"]}
    labels = document.get("labels")
    errors = validate_label_document(labels if isinstance(labels, Mapping) else {})
    if document.get("suite_id") != V12_SUITE_ID:
        errors.append("evaluator bundle suite identity is wrong")
    return {"valid": not errors, "errors": errors, "digest": canonical_digest(document)}


def information_sufficiency_audit(root: Path) -> dict[str, Any]:
    candidate = candidate_bundle_audit(root)
    evaluator = evaluator_bundle_audit(root)
    return {
        "status": "PASS" if candidate["valid"] and evaluator["valid"] else "BLOCKED_INFORMATION_SUFFICIENCY",
        "candidate_bundle": candidate,
        "evaluator_bundle": evaluator,
        "case_gates": {
            "historical_answerable_or_abstainable": candidate["valid"],
            "scikit_learn_30512_scipy_inferable": candidate["valid"],
            "pandas_45601_semantic_ambiguity_preserved": candidate["valid"],
        },
        "random_baseline": {"method": "uniform_terminal_state", "certifying": False},
        "human_packet": {"status": "REQUIRED_FOR_CERTIFICATION", "candidate_only": True},
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return cast(dict[str, Any], value)


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
        if not isinstance(platform, Mapping) or not str(platform.get("container_image", "")).startswith("mirror.gcr.io/"):
            errors.append(f"{recipe.get('case_id')}: digest-pinned base image is required")
        for side in ("control", "candidate"):
            value = recipe.get(side)
            if not isinstance(value, Mapping) or not isinstance(value.get("packages"), Mapping) or not isinstance(value.get("command"), list):
                errors.append(f"{recipe.get('case_id')}: {side} runtime is incomplete")
    return {"status": "READY" if not errors else "BLOCKED", "errors": errors, "recipe_digest": file_digest(path)}


def evaluate_v12(
    root: Path,
    *,
    candidate_command: Sequence[str] | str | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Run the external candidate protocol and score only evaluator-side data."""

    candidate_audit = candidate_bundle_audit(root)
    evaluator_audit = evaluator_bundle_audit(root)
    runtime_audit = _runtime_audit(root)
    result: dict[str, Any] = {
        "schema_version": V12_PROTOCOL_VERSION,
        "suite_id": V12_SUITE_ID,
        "release_version": V12_RELEASE_VERSION,
        "status": "BLOCKED",
        "candidate_gold_visible": False,
        "candidate_repository_visible": False,
        "network_used": False,
        "episode_ids": "evaluator-only-random-per-run",
        "candidate_bundle": candidate_audit,
        "evaluator_bundle": evaluator_audit,
        "runtime": runtime_audit,
        "artifact_root": "external-artifact-root" if artifact_root else None,
        "blockers": [],
    }
    if not candidate_audit["valid"]:
        result["blockers"].append("BLOCKED_INFORMATION_SUFFICIENCY")
    if not evaluator_audit["valid"]:
        result["blockers"].append("BLOCKED_BENCHMARK_INTEGRITY")
    if runtime_audit["status"] != "READY":
        result["blockers"].append("BLOCKED_REPRODUCIBILITY")
    if candidate_command is None:
        result["blockers"].append("CANDIDATE_COMMAND_REQUIRED")
    if result["blockers"]:
        return result
    command = candidate_command
    if command is None:
        return result

    candidate_document = _read_json(root / V12_CANDIDATE_BUNDLE_RELATIVE)
    evaluator_document = _read_json(root / V12_EVALUATOR_BUNDLE_RELATIVE)
    labels_document = cast(Mapping[str, Mapping[str, Any]], evaluator_document["labels"])
    templates = {
        str(item["template_id"]): cast(Mapping[str, Any], item["evidence"])
        for item in cast(list[Mapping[str, Any]], candidate_document["evidence_templates"])
    }
    safety_templates = {
        str(item["template_id"]): cast(Mapping[str, Any], item["evidence"])
        for item in cast(list[Mapping[str, Any]], candidate_document["safety_templates"])
    }
    mapping = generate_episode_ids()
    packets: list[CandidatePacket] = []
    ordered_case_ids = list(ALL_CASE_IDS)
    secrets.SystemRandom().shuffle(ordered_case_ids)
    for case_id in ordered_case_ids:
        if case_id.startswith("RADAR-V07-A"):
            template_id = "attribution-" + case_id[-2:]
            evidence = templates[template_id]
        else:
            evidence = safety_templates["safety-" + case_id[-2:]]
        packets.append(CandidatePacket(mapping[case_id], evidence, tuple(sorted(CAPABILITIES))))
    workspace = root / ".candidate-workspace-v1.2"
    workspace.mkdir(mode=0o700, exist_ok=True)
    try:
        protocol = ExternalCandidateProtocol(command, working_directory=workspace)
        protocol_result = protocol.run(packets)
    finally:
        try:
            workspace.rmdir()
        except OSError:
            pass
    result["protocol"] = {"version": V12_PROTOCOL_VERSION, "docker_isolated": protocol.docker_isolated, "network_denied": protocol_result.get("network_denied", False)}
    result["protocol_result"] = {key: value for key, value in protocol_result.items() if key != "responses"}
    if protocol_result.get("status") != "COMPLETED":
        result["blockers"].append("BLOCKED_CANDIDATE_ISOLATION")
        return result
    responses = cast(list[dict[str, Any]], protocol_result.get("responses", []))
    valid_episode_ids = set(mapping.values())
    response_runs: dict[str, Mapping[str, Any]] = {}
    protocol_errors: list[str] = []
    for response in responses:
        episode_id = response.get("episode_id")
        if episode_id not in valid_episode_ids:
            protocol_errors.append("UNKNOWN_EPISODE_ID")
            continue
        if "case_id" in response or "gold" in response or "reference" in response:
            protocol_errors.append("EVALUATOR_FIELD_IN_CANDIDATE_OUTPUT")
            continue
        response_runs[str(episode_id)] = response
    if protocol_errors:
        result["blockers"].append("BLOCKED_CANDIDATE_ISOLATION")
        result["protocol_errors"] = protocol_errors
        return result
    inverse = {episode_id: case_id for case_id, episode_id in mapping.items()}
    runs = {inverse[episode_id]: response for episode_id, response in response_runs.items()}
    result["runs"] = runs
    result["episode_count"] = len(response_runs)
    result["mapping_digest"] = canonical_digest(sorted(mapping.items()))
    result["metrics"] = score_v12(labels_document["cases"], runs)["metrics"]
    result["status"] = "COMPLETED"
    return result


def secure_temp_workspace(prefix: str = "radar-v12-") -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix=prefix)


def build_file_manifest(root: Path, paths: Iterable[Path]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in sorted((item.resolve() for item in paths), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"baseline source is not a regular file: {path}")
        records.append(
            {
                "path": path.relative_to(root.resolve()).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": file_digest(path),
            }
        )
    return {
        "files": records,
        "tree_digest": canonical_digest(records),
    }


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
    baselines = document.get("baselines")
    if not isinstance(baselines, Mapping):
        return {"status": "BLOCKED", "errors": ["baseline freeze baselines must be an object"]}
    for name, entry in baselines.items():
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
    """Project all inputs that matter; scores alone are never sufficient."""

    keys = (
        "suite_digest",
        "candidate_bundle_digest",
        "evaluator_bundle_digest",
        "safety_digest",
        "runtime_digest",
        "baseline_digest",
        "executor_capability_version",
        "candidate_protocol",
        "platform",
        "decision",
        "metrics",
        "predictions",
    )
    return {key: result.get(key) for key in keys}


def compare_exact_reference(result: Mapping[str, Any], reference: Mapping[str, Any] | None) -> dict[str, Any]:
    if reference is None:
        return {"status": "NO_REFERENCE"}
    current = exact_reference_projection(result)
    expected = exact_reference_projection(reference)
    status = "EXACT_MATCH" if current == expected else "DRIFT"
    return {
        "status": status,
        "scores_equal": current.get("metrics") == expected.get("metrics"),
        "inputs_equal": current == expected,
        "current_digest": canonical_digest(current),
        "reference_digest": canonical_digest(expected),
    }


def separation_audit(root: Path) -> dict[str, Any]:
    candidate = root / V12_CANDIDATE_BUNDLE_RELATIVE
    evaluator = root / V12_EVALUATOR_BUNDLE_RELATIVE
    errors: list[str] = []
    if not candidate.is_file():
        errors.append("candidate bundle absent")
    if not evaluator.is_file():
        errors.append("evaluator bundle absent")
    if candidate.is_file() and evaluator.is_file():
        candidate_text = candidate.read_text(encoding="utf-8").lower()
        if any(token in candidate_text for token in ("gold_evidence", "gold_provenance", "action_owner_repository")):
            errors.append("candidate bundle contains evaluator-only content")
        try:
            candidate_root = candidate.parent.resolve()
            for item in candidate_root.rglob("*"):
                if item.is_file() and "evaluator" in item.name.lower():
                    errors.append("evaluator asset is physically inside candidate bundle")
        except OSError as exc:
            errors.append(f"candidate bundle traversal failed: {type(exc).__name__}")
    return {
        "valid": not errors,
        "errors": errors,
        "candidate_digest": file_digest(candidate) if candidate.is_file() else None,
        "evaluator_digest": file_digest(evaluator) if evaluator.is_file() else None,
    }


def source_package_mirror_audit(root: Path) -> dict[str, Any]:
    """Compare repository-facing candidate resources with packaged resources."""

    pairs = (
        (root / "candidate/decisive-v1.2/candidate-bundle.json", root / "src/radar_bench/resources/candidate/decisive-v1.2/candidate-bundle.json"),
        (root / "corpus/v1.1.0/decisive-v1.2/suite.json", root / "src/radar_bench/resources/corpus/v1.1.0/decisive-v1.2/suite.json"),
        (root / "corpus/v1.1.0/decisive-v1.2/runtime-recipes.json", root / "src/radar_bench/resources/corpus/v1.1.0/decisive-v1.2/runtime-recipes.json"),
        (root / "corpus/v1.1.0/decisive-v1.2/metric-contract-v1.2.json", root / "src/radar_bench/resources/corpus/v1.1.0/decisive-v1.2/metric-contract-v1.2.json"),
    )
    mismatches: list[str] = []
    for source, packaged in pairs:
        if not source.is_file() or not packaged.is_file():
            mismatches.append(f"missing mirror: {source.name}")
            continue
        try:
            source_digest = canonical_digest(_read_json(source))
            packaged_digest = canonical_digest(_read_json(packaged))
        except (OSError, ValueError):
            source_digest = file_digest(source)
            packaged_digest = file_digest(packaged)
        if source_digest != packaged_digest:
            mismatches.append(f"digest mismatch: {source.name}")
    return {"status": "PASS" if not mismatches else "FAIL", "mismatches": mismatches, "pair_count": len(pairs)}
