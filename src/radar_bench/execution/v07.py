"""v0.7 executable investigation benchmark.

The v0.7 boundary is intentionally stricter than the v0.5 replay oracle:
experiment requests are executed in a sealed container and return observations,
never historical lookup results.  A missing or incomplete sealed corpus blocks
validation; it does not produce synthetic runs or a new replay benchmark.
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import statistics
import subprocess  # nosec B404 - fixed container argv, shell disabled
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

from radar_bench.evaluation.stages import digest_tree

PROTOCOL_VERSION = "0.7"
FROZEN_V05_COMMIT = "60ccc18"
COMMON_CAPABILITIES: tuple[str, ...] = (
    "rerun",
    "change_dependency_version",
    "freeze_dependency",
    "bisect_component",
    "toggle_environment_variable",
    "run_minimal_test",
    "inspect_dependency_graph",
)
MIN_ATTRIBUTION_CASES = 7
MIN_SAFETY_CASES = 20
MAX_CASES = 30
REQUIRED_V07_ARTIFACTS = (
    "v07-gates.json",
    "v07-manifest-validation.json",
    "v07-freeze-audit.json",
    "v07-execution-runs.json",
    "v07-preparation-audit.json",
)
FROZEN_REQUEST_MAP = {
    "baseline_check": "rerun",
    "version_swap": "change_dependency_version",
}
MAX_OUTPUT_BYTES = 10 * 1024 * 1024
FORBIDDEN_RUNTIME_TOKENS = (
    "gold",
    "historical",
    "maintainer_confirmation",
    "post_cutoff",
    "tgold",
)


def _metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _directory_digest(path: Path, root: Path) -> str:
    digest = hashlib.sha256()
    files = [item for item in path.rglob("*") if item.is_file() and ".git" not in item.parts]
    for item in sorted(files):
        digest.update(str(item.relative_to(root)).replace("\\", "/").encode("utf-8"))
        with item.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return "sha256:" + digest.hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(manifest).encode("utf-8")).hexdigest()


def _contains_forbidden_runtime_value(value: Any, path: str = "") -> list[str]:
    errors: list[str] = []
    lowered_path = path.lower()
    if any(token in lowered_path for token in FORBIDDEN_RUNTIME_TOKENS):
        errors.append(path or "manifest")
    if isinstance(value, Mapping):
        for key, child in value.items():
            errors.extend(_contains_forbidden_runtime_value(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_contains_forbidden_runtime_value(child, f"{path}[{index}]"))
    elif isinstance(value, str) and any(token in value.lower() for token in FORBIDDEN_RUNTIME_TOKENS):
        errors.append(path or "manifest")
    return errors


def _relative_path(root: Path, value: Any, field: str) -> tuple[Path | None, list[str]]:
    if not isinstance(value, str) or not value:
        return None, [f"{field} must be a non-empty relative path"]
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None, [f"{field} must stay inside the sealed corpus"]
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None, [f"{field} escapes the sealed corpus"]
    return resolved, []


def _argv(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        return [f"{field} must be a non-empty argv list"]
    if any(item in {"--network", "--privileged", "-v", "--volume"} for item in value):
        return [f"{field} cannot override container isolation"]
    return []


def _validate_case(case: Mapping[str, Any], root: Path, index: int) -> list[str]:
    prefix = f"cases[{index}]"
    errors: list[str] = []
    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        errors.append(f"{prefix}.case_id is required")
    if case.get("corpus_kind") not in {"attribution", "safety"}:
        errors.append(f"{prefix}.corpus_kind must be attribution or safety")
    platform_spec = case.get("platform")
    if not isinstance(platform_spec, Mapping):
        errors.append(f"{prefix}.platform is required")
    else:
        if platform_spec.get("os") != "linux":
            errors.append(f"{prefix}.platform.os must be linux")
        if platform_spec.get("architecture") != "x86_64":
            errors.append(f"{prefix}.platform.architecture must be x86_64")
        image = platform_spec.get("container_image")
        if not isinstance(image, str) or "@sha256:" not in image:
            errors.append(f"{prefix}.platform.container_image must be digest-pinned")

    view_path, view_errors = _relative_path(root, case.get("candidate_view"), f"{prefix}.candidate_view")
    errors.extend(view_errors)
    if view_path is not None:
        if not view_path.is_file():
            errors.append(f"{prefix}.candidate_view does not exist")
        elif case.get("candidate_view_digest") != _sha256(view_path):
            errors.append(f"{prefix}.candidate_view_digest does not match")

    for side in ("control", "candidate"):
        spec = case.get(side)
        side_prefix = f"{prefix}.{side}"
        if not isinstance(spec, Mapping):
            errors.append(f"{side_prefix} is required")
            continue
        workspace, workspace_errors = _relative_path(root, spec.get("workspace"), f"{side_prefix}.workspace")
        errors.extend(workspace_errors)
        if workspace is not None and not workspace.is_dir():
            errors.append(f"{side_prefix}.workspace does not exist")
        source_digest = spec.get("source_digest")
        if not isinstance(source_digest, str) or not source_digest.startswith("sha256:"):
            errors.append(f"{side_prefix}.source_digest is required")
        elif workspace is not None and workspace.is_dir() and source_digest != _directory_digest(workspace, root):
            errors.append(f"{side_prefix}.source_digest does not match workspace contents")
        revision = spec.get("revision")
        if not isinstance(revision, str) or len(revision) < 7:
            errors.append(f"{side_prefix}.revision must identify the exact prepared revision")
        errors.extend(_argv(spec.get("command"), f"{side_prefix}.command"))
        environment = spec.get("environment")
        if not isinstance(environment, Mapping) or not all(isinstance(key, str) and isinstance(value, str) for key, value in environment.items()):
            errors.append(f"{side_prefix}.environment must be a string map")

    recipes = case.get("capability_recipes")
    if not isinstance(recipes, Mapping) or set(recipes) != set(COMMON_CAPABILITIES):
        errors.append(f"{prefix}.capability_recipes must cover the common capability surface exactly")
    else:
        for capability in COMMON_CAPABILITIES:
            recipe = recipes[capability]
            if not isinstance(recipe, Mapping):
                errors.append(f"{prefix}.capability_recipes.{capability} must be an object")
                continue
            errors.extend(_argv(recipe.get("control_command"), f"{prefix}.capability_recipes.{capability}.control_command"))
            errors.extend(_argv(recipe.get("candidate_command"), f"{prefix}.capability_recipes.{capability}.candidate_command"))

    prepared = case.get("prepared_artifacts")
    if not isinstance(prepared, list) or not prepared:
        errors.append(f"{prefix}.prepared_artifacts must contain local artifacts")
    else:
        for artifact_index, artifact in enumerate(prepared):
            if not isinstance(artifact, Mapping):
                errors.append(f"{prefix}.prepared_artifacts[{artifact_index}] must be an object")
                continue
            artifact_path, artifact_errors = _relative_path(root, artifact.get("path"), f"{prefix}.prepared_artifacts[{artifact_index}].path")
            errors.extend(artifact_errors)
            if artifact_path is not None:
                if not artifact_path.is_file():
                    errors.append(f"{prefix}.prepared_artifacts[{artifact_index}].path does not exist")
                elif artifact.get("digest") != _sha256(artifact_path):
                    errors.append(f"{prefix}.prepared_artifacts[{artifact_index}].digest does not match")
    return errors


def validate_manifest(manifest: Mapping[str, Any], *, root: Path) -> list[str]:
    """Validate a sealed execution manifest without loading evaluator gold."""

    errors: list[str] = []
    if manifest.get("schema_version") != PROTOCOL_VERSION:
        errors.append("manifest has the wrong protocol version")
    policy = manifest.get("evaluation_policy")
    expected_policy = {
        "network": "denied",
        "gold_mounted": False,
        "historical_evidence_mounted": False,
        "artifact_policy": "local_only",
        "shell": False,
    }
    if policy != expected_policy:
        errors.append("evaluation_policy must enforce network denied, no gold/history, local artifacts, and shell false")
    if tuple(manifest.get("capabilities", ())) != COMMON_CAPABILITIES:
        errors.append("capabilities must equal the common v0.7 interface")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) > MAX_CASES:
        errors.append(f"cases must be a list of at most {MAX_CASES} sealed cases")
        cases = []
    elif cases and manifest.get("manifest_status") != "SEALED":
        errors.append("manifest_status must be SEALED before any case can execute")
    case_ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            errors.append(f"cases[{index}] must be an object")
            continue
        case_id = case.get("case_id")
        if isinstance(case_id, str):
            if case_id in case_ids:
                errors.append(f"duplicate case id: {case_id}")
            case_ids.add(case_id)
        errors.extend(_validate_case(case, root, index))
    forbidden = _contains_forbidden_runtime_value({key: value for key, value in manifest.items() if key not in {"preparation", "evaluation_policy"}})
    if forbidden:
        errors.append("runtime manifest contains forbidden gold/history channel: " + ", ".join(sorted(set(forbidden))))
    return errors


def validate_request(request: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if request.get("schema_version") != PROTOCOL_VERSION:
        errors.append("request has the wrong protocol version")
    if not isinstance(request.get("request_id"), str) or not request["request_id"]:
        errors.append("request_id is required")
    if not isinstance(request.get("episode_id"), str) or not request["episode_id"]:
        errors.append("episode_id is required")
    if request.get("capability") not in COMMON_CAPABILITIES:
        errors.append("capability is outside the globally supported interface")
    if any(token in _canonical(request).lower() for token in FORBIDDEN_RUNTIME_TOKENS):
        errors.append("request contains forbidden gold/history content")
    return errors


def adapt_frozen_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Map unchanged v0.5 request names onto the common v0.7 capability API."""

    capability = FROZEN_REQUEST_MAP.get(str(request.get("type")))
    if capability is None:
        raise ValueError(f"frozen request type is not executable in v0.7: {request.get('type')}")
    return {
        "schema_version": PROTOCOL_VERSION,
        "request_id": request.get("request_id"),
        "episode_id": request.get("episode_id"),
        "capability": capability,
        "parameters": {
            key: request.get(key)
            for key in ("target_component", "changed_variable", "control", "candidate")
            if request.get(key) is not None
        },
    }


class HermeticExecutor:
    """Execute sealed recipes in a digest-pinned, network-denied container."""

    def __init__(self, manifest: Mapping[str, Any], *, root: Path) -> None:
        errors = validate_manifest(manifest, root=root)
        if errors:
            raise ValueError("invalid executable manifest: " + "; ".join(errors))
        self._manifest = manifest
        self._root = root.resolve()
        self._cases = {case["case_id"]: case for case in manifest.get("cases", [])}

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        errors = validate_request(request)
        if errors:
            return {"status": "INVALID_REQUEST", "error_codes": errors, "request_id": request.get("request_id")}
        case = self._cases.get(request["episode_id"])
        if case is None:
            return {"status": "EXECUTION_ERROR", "error_codes": ["CASE_NOT_SEALED"], "request_id": request["request_id"]}
        recipe = case["capability_recipes"][request["capability"]]
        control = self._run_side(case, "control", recipe["control_command"])
        candidate = self._run_side(case, "candidate", recipe["candidate_command"])
        if control["status"] != "COMPLETED" or candidate["status"] != "COMPLETED":
            return {
                "status": "EXECUTION_ERROR",
                "request_id": request["request_id"],
                "error_codes": ["CONTAINER_EXECUTION_FAILED"],
                "observations": {"control": control, "candidate": candidate},
            }
        control_pass = control["returncode"] == 0
        candidate_pass = candidate["returncode"] == 0
        if not control_pass:
            outcome = "BASELINE_NOT_STABLE"
            induced: bool | None = None
        elif control_pass != candidate_pass:
            outcome = "CANDIDATE_SPECIFIC"
            induced = not candidate_pass
        else:
            outcome = "NO_DISTINGUISHING_EFFECT"
            induced = False
        useful = control_pass != candidate_pass
        observation = {
            "control_pass": control_pass,
            "candidate_pass": candidate_pass,
            "control_output_digest": control["output_digest"],
            "candidate_output_digest": candidate["output_digest"],
            "control_duration_ms": control["duration_ms"],
            "candidate_duration_ms": candidate["duration_ms"],
        }
        return {
            "status": "COMPLETED",
            "request_id": request["request_id"],
            "adapter": "v07_hermetic_container",
            "result": {
                "outcome": outcome,
                "useful": useful,
                "supported_component": None,
                "eliminated_hypotheses": [],
                "candidate_induced": induced,
            },
            "execution_evidence": [manifest_digest(observation)],
            "observations": observation,
            "provenance_id": manifest_digest({"request": request, "observation": observation}),
        }

    def _run_side(self, case: Mapping[str, Any], side: str, command: Sequence[str]) -> dict[str, Any]:
        spec = case[side]
        workspace = (self._root / spec["workspace"]).resolve()
        image = case["platform"]["container_image"]
        docker_path = shutil.which("docker")
        if docker_path is None:
            return {"status": "EXECUTION_ERROR", "error": "DOCKER_NOT_FOUND"}
        environment = {str(key): str(value) for key, value in spec["environment"].items()}
        docker_command = [
            docker_path,
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cpus=2",
            "--memory=512m",
            "--pids-limit=256",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65532:65532",
            "--tmpfs",
            "/run/radar-tmp:rw,noexec,nosuid,nodev,mode=1777",
            "-v",
            f"{workspace.as_posix()}:/workspace:ro",
            "-w",
            "/workspace",
        ]
        docker_command.extend(item for key, value in environment.items() for item in ("-e", f"{key}={value}"))
        docker_command.extend([image, *command])
        started = time.perf_counter()
        try:
            completed = subprocess.run(  # nosec - fixed docker argv and shell disabled
                docker_command,
                cwd=self._root,
                env={"PATH": str(Path(docker_path).parent)},
                capture_output=True,
                check=False,
                shell=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "EXECUTION_ERROR", "error": type(exc).__name__}
        output_size = len(completed.stdout) + len(completed.stderr)
        if output_size > MAX_OUTPUT_BYTES:
            return {
                "status": "EXECUTION_ERROR",
                "error": "OUTPUT_LIMIT_EXCEEDED",
                "output_bytes": output_size,
            }
        return {
            "status": "COMPLETED",
            "returncode": completed.returncode,
            "output_digest": "sha256:" + hashlib.sha256(completed.stdout + completed.stderr).hexdigest(),
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }


def preparation_audit(root: Path, manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        return {
            "status": "BLOCKED_BY_EXECUTABILITY",
            "manifest": str(manifest_path),
            "case_count": 0,
            "reason": "No sealed v0.7 execution manifest exists; historical replay is not substituted.",
        }
    try:
        manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        return {"status": "BLOCKED_BY_EXECUTABILITY", "manifest": str(manifest_path), "case_count": 0, "reason": f"Manifest cannot be read: {exc}"}
    errors = validate_manifest(manifest, root=root)
    cases = manifest.get("cases", []) if isinstance(manifest.get("cases", []), list) else []
    counts = Counter(case.get("corpus_kind") for case in cases if isinstance(case, Mapping))
    if errors:
        return {"status": "BLOCKED_BY_EXECUTABILITY", "manifest": str(manifest_path), "case_count": len(cases), "counts": dict(counts), "errors": errors, "reason": "Sealed manifest validation failed."}
    if not cases:
        return {"status": "BLOCKED_BY_EXECUTABILITY", "manifest": str(manifest_path), "case_count": 0, "counts": dict(counts), "reason": "The preparation phase has not sealed any executable cases."}
    if counts["attribution"] < MIN_ATTRIBUTION_CASES or counts["safety"] < MIN_SAFETY_CASES:
        return {"status": "BLOCKED_BY_EXECUTABILITY", "manifest": str(manifest_path), "case_count": len(cases), "counts": dict(counts), "reason": f"Pilot requires at least {MIN_ATTRIBUTION_CASES} attribution and {MIN_SAFETY_CASES} safety cases."}
    if platform.system().lower() != "linux" or shutil.which("docker") is None:
        return {"status": "BLOCKED_BY_EXECUTABILITY", "manifest": str(manifest_path), "case_count": len(cases), "counts": dict(counts), "reason": "A Linux/x86-64 Docker runtime is required for network-denied hermetic execution on this host."}
    return {"status": "READY", "manifest": str(manifest_path), "case_count": len(cases), "counts": dict(counts), "manifest_digest": manifest_digest(manifest)}


def freeze_audit(root: Path, expected_digest: str, expected_commit: str = FROZEN_V05_COMMIT) -> dict[str, Any]:
    current_digest = digest_tree(root, ("src/radar_bench/investigation/*.py", "src/radar_bench/evaluation/v05.py", "schema/investigation-*.json", "scripts/run_v05_investigation.py"))
    commit_result = subprocess.run(  # nosec - fixed read-only git argv
        ["git", "log", "-1", "--format=%H", "--", "src/radar_bench/investigation/v01.py", "src/radar_bench/evaluation/v05.py", "scripts/run_v05_investigation.py"],
        cwd=root,
        capture_output=True,
        check=False,
        shell=False,
        text=True,
    )
    current_commit = commit_result.stdout.strip() if commit_result.returncode == 0 else "unknown"
    return {"expected_digest": expected_digest, "current_digest": current_digest, "digest_match": current_digest == expected_digest, "expected_commit": expected_commit, "current_commit": current_commit, "commit_match": current_commit.startswith(expected_commit), "tuning_performed": False}


def _terminal(run: Mapping[str, Any]) -> Mapping[str, Any]:
    value = run.get("terminal")
    return value if isinstance(value, Mapping) else {}


def evaluate_pilot(cases: Sequence[Mapping[str, Any]], runs: Sequence[Mapping[str, Any]], naive_runs: Sequence[Mapping[str, Any]] = (), no_experiment_runs: Sequence[Mapping[str, Any]] = (), random_runs: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Score completed executable runs against evaluator-only labels."""

    by_id = {run.get("episode_id"): run for run in runs}
    attributed_claims = [
        (case, by_id[case["case_id"]])
        for case in cases
        if case["case_id"] in by_id and _terminal(by_id[case["case_id"]]).get("state") == "CAUSALLY_ATTRIBUTED"
    ]
    owner_correct = sum(_terminal(run).get("action_owner_repository") == case.get("gold", {}).get("action_owner_repository") for case, run in attributed_claims)
    candidate_claims = [pair for pair in attributed_claims if case_gold(pair[0], "candidate_induced") is not None]
    candidate_correct = sum(_terminal(run).get("candidate_induced") == case_gold(case, "candidate_induced") for case, run in candidate_claims)
    resolution_correct = 0
    safety_total = 0
    safety_safe = 0
    premature = 0
    useful = 0
    attempts = 0
    experiment_counts: list[int] = []
    for case in cases:
        run = by_id.get(case["case_id"])
        if run is None:
            continue
        terminal = _terminal(run)
        should_abstain = bool(case.get("gold", {}).get("should_abstain"))
        claimed = terminal.get("state") == "CAUSALLY_ATTRIBUTED"
        if should_abstain:
            safety_total += 1
            safety_safe += int(not claimed)
            premature += int(claimed)
            resolution_correct += int(not claimed)
        else:
            resolution_correct += int(claimed and terminal.get("root_cause_component") == case.get("gold", {}).get("root_cause_component"))
        for attempt in run.get("attempts", []):
            attempts += 1
            useful += int(bool(attempt.get("useful")))
        experiment_counts.append(len(run.get("attempts", [])))
    naive_by_id = {run.get("episode_id"): run for run in naive_runs}
    naive_denominator = sum(1 for case in cases if case["case_id"] in naive_by_id and case.get("corpus_kind") == "attribution")
    naive_correct = sum(
        int(_terminal(naive_by_id[case["case_id"]]).get("root_cause_component") == case.get("gold", {}).get("root_cause_component"))
        for case in cases
        if case["case_id"] in naive_by_id and case.get("corpus_kind") == "attribution"
    )
    no_experiment_by_id = {run.get("episode_id"): run for run in no_experiment_runs}
    no_experiment_denominator = sum(1 for case in cases if case["case_id"] in no_experiment_by_id and case.get("corpus_kind") == "attribution")
    no_experiment_correct = sum(
        int(_terminal(no_experiment_by_id[case["case_id"]]).get("root_cause_component") == case.get("gold", {}).get("root_cause_component"))
        for case in cases
        if case["case_id"] in no_experiment_by_id and case.get("corpus_kind") == "attribution"
    )
    random_by_id = {run.get("episode_id"): run for run in random_runs}
    random_denominator = sum(1 for case in cases if case["case_id"] in random_by_id and case.get("corpus_kind") == "attribution")
    random_correct = sum(
        int(_terminal(random_by_id[case["case_id"]]).get("root_cause_component") == case.get("gold", {}).get("root_cause_component"))
        for case in cases
        if case["case_id"] in random_by_id and case.get("corpus_kind") == "attribution"
    )
    radar_resolution = _metric(resolution_correct, sum(1 for case in cases if case["case_id"] in by_id))
    no_experiment = _metric(no_experiment_correct, no_experiment_denominator)
    naive = _metric(naive_correct, naive_denominator)
    return {
        "cases": len(cases),
        "completed_runs": len(by_id),
        "action_owner_precision": _metric(owner_correct, len(attributed_claims)),
        "candidate_induced_precision": _metric(candidate_correct, len(candidate_claims)),
        "correct_resolution_or_abstention": radar_resolution,
        "safety_abstention_recall": _metric(safety_safe, safety_total),
        "premature_owner_accusations": {"value": premature, "numerator": premature, "denominator": sum(1 for case in cases if case["case_id"] in by_id)},
        "useful_experiment_rate": _metric(useful, attempts),
        "median_experiments_to_resolution": {"value": statistics.median(experiment_counts) if experiment_counts else None, "count": len(experiment_counts)},
        "naive_resolution": naive,
        "no_experiment_resolution": no_experiment,
        "random_resolution": _metric(random_correct, random_denominator),
        "advantage_over_naive": {"value": radar_resolution["value"] - naive["value"] if radar_resolution["value"] is not None and naive["value"] is not None else None},
        "advantage_over_no_experiment": {"value": radar_resolution["value"] - no_experiment["value"] if radar_resolution["value"] is not None and no_experiment["value"] is not None else None},
    }


def case_gold(case: Mapping[str, Any], field: str) -> Any:
    gold = case.get("gold", {})
    return gold.get(field) if isinstance(gold, Mapping) else None


def v07_gates(metrics: Mapping[str, Any], preparation: Mapping[str, Any], freeze: Mapping[str, Any]) -> dict[str, Any]:
    if preparation.get("status") != "READY":
        return {
            "product_validation": "BLOCKED_BY_EXECUTABILITY",
            "agentic_causal_investigation": "UNVALIDATED",
            "integrity_validated": False,
            "decision": "BLOCKED_BY_EXECUTABILITY",
            "checks": {},
            "interpretation": "No sealed independent executable corpus was available; replay evidence was not promoted.",
        }
    checks: dict[str, tuple[Any, str, float]] = {
        "action_owner_precision": (metrics.get("action_owner_precision", {}).get("value"), "min", 0.80),
        "candidate_induced_precision": (metrics.get("candidate_induced_precision", {}).get("value"), "min", 0.85),
        "correct_resolution_or_abstention": (metrics.get("correct_resolution_or_abstention", {}).get("value"), "min", 0.80),
        "safety_abstention_recall": (metrics.get("safety_abstention_recall", {}).get("value"), "min", 0.95),
        "premature_owner_accusations": (metrics.get("premature_owner_accusations", {}).get("value"), "max", 0.0),
        "useful_experiment_rate": (metrics.get("useful_experiment_rate", {}).get("value"), "min", 0.60),
        "median_experiments_to_resolution": (metrics.get("median_experiments_to_resolution", {}).get("value"), "max", 3.0),
        "naive_resolution": (metrics.get("naive_resolution", {}).get("value"), "max_strict", 0.60),
        "frozen_radar_advantage_over_naive": (metrics.get("advantage_over_naive", {}).get("value"), "min", 0.20),
        "radar_advantage_over_no_experiment": (metrics.get("advantage_over_no_experiment", {}).get("value"), "min", 0.0),
        "frozen_investigator_digest": (freeze.get("digest_match"), "boolean_true", 0.0),
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
        rendered[name] = {"value": value, "operator": operator, "threshold": threshold if operator != "boolean_true" else None, "status": status}
    valid = all(item["status"] == "pass" for item in rendered.values())
    return {
        "product_validation": "VALIDATED" if valid else "FAILED_VALIDATION",
        "agentic_causal_investigation": "VALIDATED" if valid else "FAILED_VALIDATION",
        "integrity_validated": valid,
        "decision": "CONTINUE_TO_PRODUCT" if valid else "KILL_RADAR_PRODUCT_THESIS",
        "checks": rendered,
        "interpretation": "Executable observations, not historical replay, are required for this decision.",
    }
