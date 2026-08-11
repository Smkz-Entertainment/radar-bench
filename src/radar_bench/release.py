"""Public v1.0 benchmark contract and fail-closed release evaluator.

This module deliberately treats the historical five-case run as a reference
artifact, not as live observations. A checkout can validate the contract
without having externally staged historical wheelhouses required to execute
it. Evaluation therefore reports every missing input and never substitutes the
canonical reference result.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, cast

from radar_bench.errors import ValidationError
from radar_bench.execution.canonical import CanonicalHarness
from radar_bench.execution.docker_runtime import inspect_docker_runtime
from radar_bench.execution.v07 import validate_manifest
from radar_bench.historical_runtime import (
    RUNTIME_RECIPES_RELATIVE,
    load_runtime_recipes,
    reconstruct_historical_cases,
    validate_runtime_recipes,
)
from radar_bench.schema.loader import validate_json
from radar_bench.result_contract import build_result, validate_result_document

SUITE_ID = "decisive-v1.1"
RELEASE_VERSION = "1.0.1"
SUITE_RELATIVE = Path("corpus/v1.0.1/decisive-v1.1/suite.json")
HISTORICAL_LABELS_RELATIVE = Path("corpus/v1.0.1/decisive-v1.1/evaluator-labels.json")
REFERENCE_RELATIVE = Path("reference/decisive-v1.1-result.json")
HISTORICAL_CASE_COUNT = 5
SAFETY_CASE_COUNT = 20
HISTORICAL_IDS = {
    "RADAR-V07-A01",
    "RADAR-V07-A02",
    "RADAR-V07-A03",
    "RADAR-V07-A04",
    "RADAR-V07-A05",
}
REQUIRED_REJECTION_REASONS = {
    "ARTIFACT_UNAVAILABLE",
    "PLATFORM_UNAVAILABLE",
    "HISTORICAL_BUILD_UNREPRODUCIBLE",
    "DEPENDENCY_NOT_ARCHIVED",
    "NONDETERMINISTIC",
    "REQUIRES_UNAVAILABLE_HARDWARE",
}
RUNTIME_FORBIDDEN = ("gold", "historical", "post_cutoff", "tgold")
RUNTIME_SENSITIVE = (
    "pandas",
    "scikit-learn",
    "scikit_learn",
    "scipy",
    "55137",
    "30512",
    "45601",
    "57124",
    "66085",
)
MAX_RUNTIME_FILE_BYTES = 10 * 1024 * 1024


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_digest(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    )


def _resolve_inside(root: Path, base: Path, value: str) -> tuple[Path | None, str | None]:
    candidate = Path(value)
    if candidate.is_absolute():
        return None, "path must be relative to the repository"
    resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None, "path escapes the repository"
    return resolved, None


def load_suite(root: Path) -> dict[str, Any]:
    path = root / SUITE_RELATIVE
    suite = _read_json(path)
    validate_json(suite, "decisive_suite_v1_1", root=root)
    return suite


def _artifact_status(
    manifest: Mapping[str, Any], *, artifact_root: Path | None = None
) -> dict[str, Any]:
    bundle = manifest.get("artifact_bundle")
    if not isinstance(bundle, Mapping):
        return {
            "available": False,
            "reason": "ARTIFACT_UNAVAILABLE",
            "path": "external-staging-root",
        }
    bundle_id = bundle.get("bundle_id")
    if (
        not isinstance(bundle_id, str)
        or not bundle_id
        or Path(bundle_id).is_absolute()
        or ".." in Path(bundle_id).parts
        or Path(bundle_id).name != bundle_id
        or artifact_root is None
    ):
        return {"available": False, "reason": "ARTIFACT_UNAVAILABLE", "path": "external-staging-root"}
    root = artifact_root.resolve()
    path = (root / bundle_id).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return {"available": False, "reason": "ARTIFACT_UNAVAILABLE", "path": "external-staging-root"}
    if not path.is_dir():
        return {"available": False, "reason": "ARTIFACT_UNAVAILABLE", "path": "external-staging-root"}
    files = bundle.get("files")
    if not isinstance(files, Mapping) or not files:
        return {"available": False, "reason": "ARTIFACT_UNAVAILABLE", "path": "external-staging-root"}
    mismatches: list[str] = []
    for name, expected in files.items():
        candidate = path / str(name)
        if not candidate.is_file():
            mismatches.append(str(name))
            continue
        if file_digest(candidate) != expected:
            mismatches.append(str(name))
    if mismatches:
        return {
            "available": False,
            "reason": "ARTIFACT_UNAVAILABLE",
            "path": "external-staging-root",
            "mismatches": mismatches,
        }
    return {"available": True, "reason": None, "path": "external-staging-root"}


def _audit_historical_case(
    root: Path,
    entry: Mapping[str, Any],
    base: Path,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    manifest_path, path_error = _resolve_inside(root, base, str(entry.get("manifest", "")))
    if path_error or manifest_path is None:
        errors.append(f"{entry.get('case_id', '<missing>')}: {path_error}")
        return {"case_id": entry.get("case_id"), "valid": False, "errors": errors}
    if not manifest_path.is_file():
        errors.append(f"{entry.get('case_id')}: sealed manifest is absent")
        return {"case_id": entry.get("case_id"), "valid": False, "errors": errors}
    manifest = _read_json(manifest_path)
    case_id = manifest.get("case_id")
    if case_id != entry.get("case_id"):
        errors.append(f"{entry.get('case_id')}: suite and manifest case IDs differ")
    if manifest.get("status") != "LOCALLY_SEALED":
        errors.append(f"{case_id}: manifest is not LOCALLY_SEALED")
    container = manifest.get("container", {})
    if not isinstance(container, Mapping) or container.get("network") != "none":
        errors.append(f"{case_id}: network policy is not denied")
    if not isinstance(container, Mapping) or container.get("architecture") != "x86_64":
        errors.append(f"{case_id}: historical case is not x86_64")
    execution = manifest.get("execution", {})
    if not isinstance(execution, Mapping):
        errors.append(f"{case_id}: execution record is absent")
        execution = {}
    for flag in (
        "candidate_gold_mounted",
        "candidate_historical_discussion_mounted",
        "candidate_received_control_output",
    ):
        if execution.get(flag) is not False:
            errors.append(f"{case_id}: {flag} is not false")
    fresh_one = execution.get("fresh_rerun_1")
    fresh_two = execution.get("fresh_rerun_2")
    if not isinstance(fresh_one, Mapping) or not isinstance(fresh_two, Mapping):
        errors.append(f"{case_id}: two fresh control/candidate reruns are required")
    runtime_recipe = manifest.get("runtime_recipe")
    runtime_recipe_available = isinstance(runtime_recipe, Mapping)
    artifacts = _artifact_status(manifest, artifact_root=artifact_root)
    if errors:
        return {
            "case_id": case_id,
            "manifest": str(manifest_path.relative_to(root)).replace("\\", "/"),
            "valid": False,
            "errors": errors,
            "artifacts": artifacts,
        }
    return {
        "case_id": case_id,
        "incident": manifest.get("incident"),
        "manifest": str(manifest_path.relative_to(root)).replace("\\", "/"),
        "valid": True,
        "artifacts": artifacts,
        "status": "READY"
        if artifacts["available"] and runtime_recipe_available
        else "BLOCKED",
        "block_reason": (
            artifacts["reason"]
            if not artifacts["available"]
            else None
            if runtime_recipe_available
            else "HISTORICAL_BUILD_UNREPRODUCIBLE"
        ),
        "runtime_recipe_available": runtime_recipe_available,
    }


def _audit_opacity(root: Path, paths: list[Path]) -> dict[str, Any]:
    violations: list[dict[str, str]] = []
    for base in paths:
        if not base.exists():
            violations.append({"path": str(base), "reason": "candidate-visible path is absent"})
            continue
        files = [base] if base.is_file() else [item for item in base.rglob("*") if item.is_file()]
        for path in files:
            if path.stat().st_size > MAX_RUNTIME_FILE_BYTES:
                violations.append({"path": path.name, "reason": "candidate-visible file exceeds size limit"})
                continue
            try:
                text = path.read_text(encoding="utf-8").lower()
            except UnicodeDecodeError:
                continue
            haystack = f"{path.name.lower()}\n{text}"
            for token in RUNTIME_FORBIDDEN + RUNTIME_SENSITIVE:
                if token in haystack:
                    violations.append({"path": str(path), "reason": f"opaque runtime contains {token}"})
    return {"valid": not violations, "violations": violations}


def validate_decisive_suite(
    root: Path, *, artifact_root: Path | None = None
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    suite_path = root / SUITE_RELATIVE
    try:
        suite = load_suite(root)
    except (OSError, ValueError, ValidationError) as exc:
        return {"valid": False, "errors": [str(exc)], "warnings": []}
    base = suite_path.parent
    historical_results: list[dict[str, Any]] = []
    for entry in cast(list[dict[str, Any]], suite["historical_cases"]):
        result = _audit_historical_case(root, entry, base, artifact_root)
        historical_results.append(result)
        errors.extend(result.get("errors", []))
    if {item.get("case_id") for item in historical_results} != HISTORICAL_IDS:
        errors.append("decisive-v1.1 historical case IDs do not match the five sealed cases")

    historical_labels_path = root / HISTORICAL_LABELS_RELATIVE
    historical_labels: dict[str, Any] = {}
    if not historical_labels_path.is_file():
        errors.append(f"historical evaluator labels are absent: {HISTORICAL_LABELS_RELATIVE}")
    else:
        try:
            historical_labels = _read_json(historical_labels_path)
        except (OSError, ValueError) as exc:
            errors.append(f"historical evaluator labels: {exc}")
    historical_label_cases = historical_labels.get("cases", {})
    if not isinstance(historical_label_cases, Mapping) or set(historical_label_cases) != HISTORICAL_IDS:
        errors.append("historical evaluator labels must contain exactly the five sealed cases")

    runtime_validation = validate_runtime_recipes(root)
    errors.extend(runtime_validation.get("errors", []))
    runtime_recipe_by_case: dict[str, str] = {}
    runtime_image_by_case: dict[str, str] = {}
    if runtime_validation.get("valid"):
        try:
            runtime_document = load_runtime_recipes(root)
            for item in cast(list[dict[str, Any]], runtime_document["recipes"]):
                case_id = str(item["case_id"])
                runtime_recipe_by_case[case_id] = str(item["recipe_id"])
                platform = item.get("platform")
                if isinstance(platform, Mapping) and isinstance(platform.get("container_image"), str):
                    runtime_image_by_case[case_id] = str(platform["container_image"])
        except (OSError, ValueError, KeyError, TypeError):
            errors.append("runtime recipe document could not be indexed")
    for entry, historical in zip(
        cast(list[dict[str, Any]], suite["historical_cases"]), historical_results
    ):
        manifest_path, manifest_error = _resolve_inside(root, base, str(entry.get("manifest", "")))
        if manifest_error or manifest_path is None or not manifest_path.is_file():
            continue
        try:
            manifest = _read_json(manifest_path)
        except (OSError, ValueError):
            continue
        pointer = manifest.get("runtime_recipe")
        expected_recipe = runtime_recipe_by_case.get(str(entry.get("case_id")))
        if (
            not isinstance(pointer, Mapping)
            or not isinstance(pointer.get("recipe_id"), str)
            or pointer.get("recipe_id") != expected_recipe
        ):
            errors.append(f"{entry.get('case_id')}: sealed manifest runtime recipe pointer is missing or mismatched")
        container = manifest.get("container")
        if (
            not isinstance(container, Mapping)
            or container.get("image") != runtime_image_by_case.get(str(entry.get("case_id")))
        ):
            errors.append(f"{entry.get('case_id')}: sealed manifest image does not match its runtime recipe")

    safety = cast(dict[str, Any], suite["safety_cases"])
    runtime_path, runtime_error = _resolve_inside(root, base, safety["runtime_manifest"])
    labels_path, labels_error = _resolve_inside(root, base, safety["evaluator_labels"])
    if runtime_error or runtime_path is None:
        errors.append(f"safety runtime manifest: {runtime_error}")
        runtime = {}
    else:
        try:
            runtime = _read_json(runtime_path)
            errors.extend(validate_manifest(runtime, root=root))
        except (OSError, ValueError) as exc:
            errors.append(f"safety runtime manifest: {exc}")
            runtime = {}
    if labels_error or labels_path is None:
        errors.append(f"evaluator labels: {labels_error}")
        labels = {}
    else:
        try:
            labels = _read_json(labels_path)
        except (OSError, ValueError) as exc:
            errors.append(f"evaluator labels: {exc}")
            labels = {}
    cases = runtime.get("cases", []) if isinstance(runtime, Mapping) else []
    if len(cases) != SAFETY_CASE_COUNT or any(item.get("corpus_kind") != "safety" for item in cases):
        errors.append("safety runtime manifest must contain exactly 20 safety cases")
    label_cases = labels.get("cases", {}) if isinstance(labels, Mapping) else {}
    if not isinstance(label_cases, Mapping) or len(label_cases) != SAFETY_CASE_COUNT:
        errors.append("evaluator labels must contain exactly 20 labels")
    elif any(item.get("should_abstain") is not True for item in label_cases.values() if isinstance(item, Mapping)):
        errors.append("every safety twin must have an evaluator abstention label")

    baseline_audit: list[dict[str, Any]] = []
    for baseline in cast(list[dict[str, Any]], suite["baselines"]):
        source = str(baseline["source"])
        if source.startswith("git:"):
            baseline_audit.append({"id": baseline["id"], "valid": source == "git:60ccc18", "source": source})
            if source != "git:60ccc18":
                errors.append(f"baseline {baseline['id']} is not frozen at 60ccc18")
            continue
        source_path = (root / source).resolve()
        try:
            source_path.relative_to(root.resolve())
        except ValueError:
            errors.append(f"baseline {baseline['id']} source escapes the repository")
            continue
        digest = file_digest(source_path) if source_path.is_file() else None
        valid = digest == baseline.get("source_digest")
        baseline_audit.append({"id": baseline["id"], "valid": valid, "source": source, "digest": digest})
        if not valid:
            errors.append(f"baseline {baseline['id']} source digest does not match")

    visible_paths: list[Path] = []
    for value in ("../safety-twins/runtime", "../safety-twins/views"):
        resolved, path_error = _resolve_inside(root, base, value)
        if path_error or resolved is None:
            errors.append(f"candidate-visible path {value}: {path_error}")
        else:
            visible_paths.append(resolved)
    opacity = _audit_opacity(root, visible_paths)
    if not opacity["valid"]:
        errors.append("candidate-visible safety runtime is not opaque")

    reference_path = root / REFERENCE_RELATIVE
    if not reference_path.is_file():
        errors.append(f"canonical reference is absent: {REFERENCE_RELATIVE}")
        reference = {}
    else:
        try:
            reference = _read_json(reference_path)
            validate_result_document(reference, root)
        except (OSError, ValueError) as exc:
            errors.append(f"canonical reference: {exc}")
            reference = {}
    reference_cases = reference.get("cases", {})
    if not isinstance(reference_cases, Mapping) or reference_cases.get("requested") != HISTORICAL_CASE_COUNT + SAFETY_CASE_COUNT:
        errors.append("canonical reference must describe exactly 25 cases")
    return {
        "suite_id": suite.get("suite_id"),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "suite_path": str(SUITE_RELATIVE).replace("\\", "/"),
        "historical": historical_results,
        "safety": {
            "count": len(cases),
            "runtime_manifest": "corpus/v1.0.1/safety-twins/runtime-manifest.json" if runtime_path else None,
            "evaluator_labels_outside_runtime": bool(labels_path and labels_path not in visible_paths),
        },
        "opacity": opacity,
        "reference_digest": file_digest(reference_path) if reference_path.is_file() else None,
        "source_digests": {
            "suite": file_digest(suite_path) if suite_path.is_file() else None,
            "runtime_manifest": file_digest(runtime_path) if runtime_path and runtime_path.is_file() else None,
            "evaluator_labels": file_digest(labels_path) if labels_path and labels_path.is_file() else None,
            "historical_evaluator_labels": file_digest(historical_labels_path) if historical_labels_path.is_file() else None,
        },
        "baseline_audit": baseline_audit,
        "runtime_recipes": {
            "path": str(RUNTIME_RECIPES_RELATIVE).replace("\\", "/"),
            "valid": bool(runtime_validation.get("valid")),
            "digest": runtime_validation.get("recipe_digest"),
            "count": runtime_validation.get("recipe_count", 0),
        },
    }


def _empty_metric(denominator: int) -> dict[str, Any]:
    return {"value": None, "numerator": None, "denominator": denominator, "status": "not_evaluable"}


def _empty_metrics() -> dict[str, Any]:
    return {
        "historical_positive_resolution": _empty_metric(5),
        "candidate_induced_correctness": _empty_metric(5),
        "action_owner_correctness": _empty_metric(5),
        "cross_repository_resolution": _empty_metric(1),
        "semantic_ambiguity_handling": _empty_metric(1),
        "safety_abstention_recall": _empty_metric(20),
        "false_owner_accusation_rate": _empty_metric(20),
        "premature_owner_accusations": _empty_metric(20),
        "useful_experiment_rate": _empty_metric(40),
        "median_substantive_experiments": _empty_metric(1),
        "advantage_over_naive_positive_resolution": _empty_metric(5),
    }


def _blocked_cases(audit: Mapping[str, Any], reason: str) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for historical in cast(list[dict[str, Any]], audit.get("historical", [])):
        cases.append({"case_id": str(historical.get("case_id")), "reason": historical.get("block_reason") or reason})
    safety_count = int(cast(dict[str, Any], audit.get("safety", {})).get("count", 0))
    cases.extend({"case_id": f"RADAR-V07-T{i:02d}", "reason": reason} for i in range(1, safety_count + 1))
    return cases


def _archived_decisive_suite_legacy(
    root: Path,
    *,
    command: list[str] | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    audit = validate_decisive_suite(root, artifact_root=artifact_root)
    now = datetime.now(timezone.utc).isoformat()
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "suite_id": SUITE_ID,
        "release_version": RELEASE_VERSION,
        "status": "INVALID" if not audit["valid"] else "BLOCKED",
        "certification": "INCONCLUSIVE",
        "timestamp": now,
        "command": command or ["radar-bench", "evaluate", "--suite", SUITE_ID],
        "platform": {
            "os": sys.platform,
            "machine": platform.machine(),
            "python": platform.python_version(),
            "docker": False,
            "canonical_supported": False,
        },
        "cases": {
            "requested": HISTORICAL_CASE_COUNT + SAFETY_CASE_COUNT,
            "executed": 0,
            "blocked": HISTORICAL_CASE_COUNT + SAFETY_CASE_COUNT,
            "blocked_cases": [],
        },
        "baselines": {
            baseline: {"status": "NOT_EXECUTED", "metrics": _empty_metrics()}
            for baseline in ("static-v0.4", "naive-deterministic", "agentic-v0.5-frozen")
        },
        "audit": audit,
        "reference": {
            "path": str(REFERENCE_RELATIVE).replace("\\", "/"),
            "used_as_runtime_evidence": False,
        },
    }
    if not audit["valid"]:
        result["error"] = "suite validation failed; no cases executed"
        result["cases"]["blocked_cases"] = _blocked_cases(audit, "INVALID_SUITE")
        return result
    reasons: list[str] = []
    reasons.extend(
        str(item["block_reason"])
        for item in cast(list[dict[str, Any]], audit["historical"])
        if item.get("block_reason")
    )
    reasons = list(dict.fromkeys(reasons))
    if reasons:
        result["cases"]["blocked_cases"] = _blocked_cases(audit, reasons[0])
        result["blockers"] = reasons
        result["error"] = "canonical executable evaluation is blocked; missing inputs were not replaced"
        for baseline in result["baselines"].values():
            baseline["status"] = "BLOCKED"
        return result
    runtime = inspect_docker_runtime()
    result["platform"].update(
        {
            "docker": runtime.available,
            "canonical_supported": runtime.supported,
            "engine_os": runtime.engine_os,
            "engine_architecture": runtime.engine_architecture,
            "runtime_reason": runtime.reason,
        }
    )
    if not result["platform"]["canonical_supported"]:
        reasons.append(
            "RUNTIME_UNAVAILABLE"
            if not runtime.available
            else "PLATFORM_UNAVAILABLE"
        )
    if reasons:
        result["cases"]["blocked_cases"] = _blocked_cases(audit, reasons[0])
        result["blockers"] = list(dict.fromkeys(reasons))
        result["error"] = "canonical executable evaluation is blocked; missing inputs were not replaced"
        for baseline in result["baselines"].values():
            baseline["status"] = "BLOCKED"
        return result
    historical_runtime = reconstruct_historical_cases(root, artifact_root)
    result["historical_runtime"] = historical_runtime
    if historical_runtime.get("status") != "READY":
        result["error"] = "historical runtime reconstruction is blocked; canonical results were not substituted"
        runtime_blockers = [str(item) for item in historical_runtime.get("blockers", [])]
        result["blockers"] = runtime_blockers or ["HISTORICAL_BUILD_UNREPRODUCIBLE"]
        result["cases"]["blocked_cases"] = _blocked_cases(
            audit, result["blockers"][0]
        )
        for baseline in result["baselines"].values():
            baseline["status"] = "BLOCKED"
        return result
    harness = CanonicalHarness(root, artifact_root).run(historical_runtime)
    result["harness"] = harness
    if harness.get("status") != "COMPLETED":
        result["error"] = "canonical execution harness is blocked; canonical results were not substituted"
        result["blockers"] = list(harness.get("blockers", [])) or ["EXECUTOR_HARNESS_UNAVAILABLE"]
        result["cases"]["blocked_cases"] = _blocked_cases(audit, result["blockers"][0])
        for baseline in result["baselines"].values():
            baseline["status"] = "BLOCKED"
        return result
    scored = cast(dict[str, Any], harness.get("metrics", {}))
    result["baselines"] = cast(dict[str, Any], scored.get("lanes", {}))
    result["cases"]["executed"] = HISTORICAL_CASE_COUNT + SAFETY_CASE_COUNT
    result["cases"]["blocked"] = 0
    result["cases"]["blocked_cases"] = []
    result["blockers"] = []
    result["status"] = "COMPLETED"
    result["certification"] = "UNSAFE"
    result["canonical_reproduction"] = {
        "status": "MATCHED_NEGATIVE_CONCLUSION"
        if (
            result["baselines"].get("static-v0.4", {}).get("metrics", {}).get("historical_positive_resolution", {}).get("numerator") == 4
            and result["baselines"].get("agentic-v0.5-frozen", {}).get("metrics", {}).get("historical_positive_resolution", {}).get("numerator") == 1
            and result["baselines"].get("agentic-v0.5-frozen", {}).get("metrics", {}).get("safety_abstention_recall", {}).get("numerator") == 20
            and scored.get("mandatory_case_gates", {}).get("scikit-learn-30512-resolves-to-scipy") is False
            and scored.get("mandatory_case_gates", {}).get("pandas-45601-keeps-semantic-ambiguity-open") is True
        )
        else "RESULT_MISMATCH",
        "reference_used_as_runtime_evidence": False,
    }
    result["release_ready"] = result["canonical_reproduction"]["status"] == "MATCHED_NEGATIVE_CONCLUSION"
    result["decision"] = "CANONICAL_NEGATIVE_REPRODUCED" if result["release_ready"] else "CANONICAL_RESULT_MISMATCH"
    return result


def evaluate_decisive_suite(
    root: Path,
    *,
    command: list[str] | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Execute decisive-v1.1 and return only the strict result contract."""

    del command  # The strict contract intentionally omits host-specific argv.
    audit = validate_decisive_suite(root, artifact_root=artifact_root)
    platform_result: dict[str, Any] = {"engine_os": "unknown", "engine_architecture": "unknown"}
    raw: dict[str, Any] = {
        "status": "INVALID" if not audit["valid"] else "BLOCKED",
        "cases": {
            "requested": HISTORICAL_CASE_COUNT + SAFETY_CASE_COUNT,
            "executed": 0,
            "blocked": HISTORICAL_CASE_COUNT + SAFETY_CASE_COUNT,
            "blocked_cases": [],
        },
        "metrics": {"lanes": {}},
        "harness": {"network_used": False},
    }
    if not audit["valid"]:
        raw["cases"]["blocked_cases"] = _blocked_cases(audit, "INVALID_SUITE")
        return build_result(root, raw=raw, audit=audit, platform=platform_result)

    reasons = list(dict.fromkeys(
        str(item["block_reason"])
        for item in cast(list[dict[str, Any]], audit.get("historical", []))
        if item.get("block_reason")
    ))
    if reasons:
        raw["cases"]["blocked_cases"] = _blocked_cases(audit, reasons[0])
        return build_result(root, raw=raw, audit=audit, platform=platform_result)

    runtime = inspect_docker_runtime()
    platform_result.update({
        "engine_os": runtime.engine_os or "unknown",
        "engine_architecture": runtime.engine_architecture or "unknown",
    })
    if not runtime.supported:
        reason = "RUNTIME_UNAVAILABLE" if not runtime.available else "PLATFORM_UNAVAILABLE"
        raw["cases"]["blocked_cases"] = _blocked_cases(audit, reason)
        return build_result(root, raw=raw, audit=audit, platform=platform_result)

    historical_runtime = reconstruct_historical_cases(root, artifact_root)
    raw["historical_runtime"] = historical_runtime
    if historical_runtime.get("status") != "READY":
        blockers = [str(item) for item in historical_runtime.get("blockers", [])]
        reason = blockers[0] if blockers else "HISTORICAL_BUILD_UNREPRODUCIBLE"
        raw["cases"]["blocked_cases"] = _blocked_cases(audit, reason)
        return build_result(root, raw=raw, audit=audit, platform=platform_result)

    harness = CanonicalHarness(root, artifact_root).run(historical_runtime)
    raw["harness"] = harness
    if harness.get("status") != "COMPLETED":
        blockers = list(harness.get("blockers", [])) or ["EXECUTOR_HARNESS_UNAVAILABLE"]
        raw["cases"]["blocked_cases"] = _blocked_cases(audit, str(blockers[0]))
        return build_result(root, raw=raw, audit=audit, platform=platform_result)

    raw["cases"].update({"executed": 25, "blocked": 0, "blocked_cases": []})
    raw["case_records"] = harness.get("cases", [])
    raw["lanes"] = harness.get("lanes", {})
    raw["metrics"] = harness.get("metrics", {})
    raw["status"] = "COMPLETED"
    reference_path = root / REFERENCE_RELATIVE
    reference: dict[str, Any] | None = None
    reference_digest: str | None = None
    if reference_path.is_file():
        try:
            loaded = cast(dict[str, Any], json.loads(reference_path.read_text(encoding="utf-8")))
            validate_result_document(loaded, root)
            reference = loaded
            reference_digest = file_digest(reference_path)
        except (OSError, ValueError, ValidationError):
            reference = None
    result = build_result(
        root,
        raw=raw,
        audit=audit,
        platform=platform_result,
        reference=reference,
        reference_digest=reference_digest,
    )
    if result["canonical_reproduction"]["status"] == "RESULT_MISMATCH":
        result["status"] = "DRIFT"
    validate_result_document(result, root)
    return result


def write_evaluation(root: Path, output: Path) -> dict[str, Any]:
    result = evaluate_decisive_suite(root)
    _write_json(output, result)
    return result


def inspect_case(root: Path, case_id: str) -> dict[str, Any]:
    suite = load_suite(root)
    for entry in cast(list[dict[str, Any]], suite["historical_cases"]):
        if entry["case_id"] == case_id:
            return {"case": entry, "runtime_visible": False, "gold_loaded": False}
    safety = suite["safety_cases"]
    if case_id.startswith("RADAR-V07-T"):
        index = int(case_id.rsplit("T", 1)[1])
        if 1 <= index <= SAFETY_CASE_COUNT:
            return {
                "case": {"case_id": case_id, "case_type": safety["case_type"]},
                "runtime_visible": True,
                "gold_loaded": False,
            }
    raise ValueError(f"unknown decisive-v1.1 case: {case_id}")
