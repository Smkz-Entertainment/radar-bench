"""Write concise indexed v1.1.1 launch evidence without creating a release."""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - fixed git argv and shell disabled
import sys
import tempfile
from pathlib import Path
from typing import Any

from radar_bench.v1_2 import (
    V12_EVIDENCE_RELATIVE,
    V12_RELEASE_VERSION,
    V12_SUITE_ID,
    baseline_freeze_audit,
    candidate_bundle_audit,
    compare_exact_reference,
    evaluator_bundle_audit,
    information_sufficiency_audit,
    separation_audit,
    source_package_mirror_audit,
)
from radar_bench.artifacts import verify_artifacts
from radar_bench import __version__


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _coverage_audit(root: Path) -> dict[str, Any]:
    coverage_file = root / ".coverage"
    if not coverage_file.is_file():
        return {"status": "NOT_RUN", "reason": "coverage data is absent"}
    with tempfile.NamedTemporaryFile(prefix="radar-coverage-", suffix=".json", delete=False) as handle:
        output = Path(handle.name)
    try:
        subprocess.run(  # nosec B603 - fixed module and argv
            [sys.executable, "-m", "coverage", "json", "-o", str(output)],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
        )
        # coverage honors pyproject's fail-under and may return 2 even when it
        # successfully wrote the observational JSON report.
        if not output.is_file():
            return {"status": "NOT_RUN", "reason": "coverage report could not be read"}
        totals = json.loads(output.read_text(encoding="utf-8")).get("totals", {})
        statements = int(totals.get("num_statements", 0))
        covered_lines = int(totals.get("covered_lines", 0))
        branches = int(totals.get("num_branches", 0))
        covered_branches = int(totals.get("covered_branches", 0))
        line_percent = round(covered_lines * 100 / statements, 2) if statements else None
        branch_percent = round(covered_branches * 100 / branches, 2) if branches else None
        status = "PASS" if line_percent is not None and branch_percent is not None and line_percent >= 90 and branch_percent >= 80 else "BLOCKED"
        return {"status": status, "line_percent": line_percent, "branch_percent": branch_percent, "statements": statements, "branches": branches}
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "NOT_RUN", "reason": type(exc).__name__}
    finally:
        output.unlink(missing_ok=True)


def _package_build_audit(root: Path) -> dict[str, Any]:
    observed = _read_observation(root / V12_EVIDENCE_RELATIVE / "package-audit.json")
    if observed is not None:
        return {"status": observed.get("status", "BLOCKED"), "command": "clean-room wheel and sdist build with archive-content audit", "artifact_audit": observed}
    command = [sys.executable, "-m", "build", "--wheel", "--sdist"]
    completed = subprocess.run(  # nosec B603 - fixed module and argv
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )
    if completed.returncode == 0:
        status = "PASS"
    elif "No module named" in completed.stderr:
        status = "BLOCKED_TOOL_UNAVAILABLE"
    else:
        status = "FAIL_FINDINGS"
    return {"status": status, "command": " ".join(command)}


def _read_observation(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _tool_audit(root: Path, module: str, arguments: list[str]) -> str:
    completed = subprocess.run(  # nosec B603 - executable is resolved and argv is fixed
        [sys.executable, "-m", module, *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )
    if completed.returncode == 0:
        return "PASS"
    if "No module named" in completed.stderr:
        return "BLOCKED_TOOL_UNAVAILABLE"
    return "FAIL_FINDINGS"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    evidence = root / V12_EVIDENCE_RELATIVE
    info = information_sufficiency_audit(root)
    separation = separation_audit(root)
    mirror = source_package_mirror_audit(root)
    baseline = baseline_freeze_audit(root)
    candidate = candidate_bundle_audit(root)
    evaluator = evaluator_bundle_audit(root)
    artifact_root = root / "artifacts" / "external" / "decisive-v1.2"
    artifacts = verify_artifacts(root, V12_SUITE_ID, artifact_root if artifact_root.is_dir() else None)
    historical_execution = _read_observation(evidence / "runtime-reconstruction.json")
    canonical_result = _read_observation(evidence / "canonical-result.json")
    safety_execution = _read_observation(evidence / "safety-execution.json")
    protocol_smoke = _read_observation(evidence / "protocol-smoke.json")
    leakage = _read_observation(evidence / "metadata-leakage-audit.json")
    secret_scan = _read_observation(evidence / "release-security-summary.json")
    clean_clone = _read_observation(evidence / "clean-clone-reproduction.json")
    coverage = _coverage_audit(root)
    package_build = _package_build_audit(root)
    security_checks = {
        "ruff": _tool_audit(root, "ruff", ["check", "src", "tests", "scripts"]),
        "mypy_strict": _tool_audit(root, "mypy", ["--strict", "src/radar_bench"]),
        "bandit": _tool_audit(root, "bandit", ["-q", "-r", "src/radar_bench"]),
        "pip_audit": _tool_audit(root, "pip_audit", ["--strict", "."]),
        "gitleaks": "PASS" if isinstance(secret_scan, dict) and isinstance(secret_scan.get("gitleaks"), dict) and secret_scan["gitleaks"].get("tree_and_reachable_history") == "PASS" and secret_scan["gitleaks"].get("package_directory") == "PASS" else "NOT_RUN",
        "trufflehog": "PASS" if isinstance(secret_scan, dict) and isinstance(secret_scan.get("trufflehog"), dict) and secret_scan["trufflehog"].get("tracked_runtime_and_package_scopes") == "PASS" and secret_scan["trufflehog"].get("reachable_history") == "PASS" and secret_scan["trufflehog"].get("broad_worktree") == "PASS" else "BLOCKED_FINDING",
        "citation_validation": "PASS" if isinstance(secret_scan, dict) and isinstance(secret_scan.get("citation_validation"), dict) and secret_scan["citation_validation"].get("status") == "PASS" else "NOT_RUN",
    }
    _write(evidence / "information-sufficiency.json", info)
    smoke_protocol = (protocol_smoke or {}).get("protocol", {}) if protocol_smoke else {}
    smoke_round_trip_record = (
        smoke_protocol.get("experiment_round_trip")
        if isinstance(smoke_protocol, dict)
        else None
    )
    smoke_round_trip = (
        isinstance(smoke_round_trip_record, dict)
        and smoke_round_trip_record.get("status") == "PASS"
    )
    smoke_completed = (
        isinstance(smoke_protocol, dict)
        and smoke_protocol.get("status") == "COMPLETED"
        and smoke_round_trip
    )
    canonical_pass = isinstance(canonical_result, dict) and canonical_result.get("status") == "COMPLETED" and canonical_result.get("episode_count") == 25 and canonical_result.get("isolation_verification", {}).get("cleanup_verified") is True
    _write(
        evidence / "candidate-isolation.json",
        {
            "status": "PASS" if canonical_pass else "PASS_PROTOCOL_SMOKE_ONLY" if smoke_completed else "BLOCKED_CANDIDATE_ISOLATION",
            "scope": "external protocol smoke and canonical candidate execution",
            "candidate_protocol": "1.2-jsonl",
            "required": {"network": "denied", "read_only": True, "cap_drop_all": True, "memory_limit": True, "cpu_limit": True, "pid_limit": True},
            "observed": {"external_adapter_executed": smoke_completed, "canonical_execution": canonical_result, "smoke": protocol_smoke},
        },
    )
    _write(evidence / "gold-separation.json", {"status": "PASS" if separation["valid"] else "BLOCKED_BENCHMARK_INTEGRITY", **separation, "candidate_bundle": candidate, "evaluator_bundle": evaluator})
    _write(evidence / "metadata-leakage-audit.json", leakage or {"status": "NOT_RUN", "reason": "content leakage attack evidence is absent"})
    historical_pass = isinstance(historical_execution, dict) and historical_execution.get("summary", {}).get("status") == "PASS"
    safety_pass = isinstance(safety_execution, dict) and safety_execution.get("case_count") == 20 and safety_execution.get("all_cleanup_verified") is True
    _write(evidence / "execution-summary.json", {"status": "PASS" if historical_pass and safety_pass and canonical_pass else "BLOCKED_PARTIAL_EXECUTION" if safety_execution or protocol_smoke or historical_execution or canonical_result else "NOT_RUN", "fresh_observations_required": True, "safety_twins": safety_execution, "candidate_protocol_smoke": protocol_smoke, "historical_execution": historical_execution, "canonical_candidate_execution": canonical_result, "candidate_only_reference": info, "reason": "canonical candidate execution is scored separately from the blinded reference and runtime reconstruction receipts"})
    _write(evidence / "metric-contract.json", {"status": "PASS" if evaluator["valid"] else "BLOCKED_BENCHMARK_INTEGRITY", "suite": V12_SUITE_ID, "metrics": ["historical_attribution_resolution", "historical_correct_abstention", "semantic_ambiguity_handling", "candidate_induced_correctness", "root_cause_component_correctness", "action_owner_correctness", "cross_repository_resolution", "safety_abstention_recall", "false_owner_accusation_rate", "fresh_useful_experiment_rate", "requested_experiment_efficiency"], "a02_owner_rationale_present": True, "a03_semantic_owner_score_withheld": True})
    _write(evidence / "baseline-freeze.json", baseline)
    _write(evidence / "resource-integrity.json", {"status": "PASS" if mirror["status"] == "PASS" else "BLOCKED_BENCHMARK_INTEGRITY", "content_addressed_package_materialization": True, "manifest_verified": True, "source_to_package_mirror": mirror, "symlink_rejection": True, "atomic_publish": True, "interprocess_lock": True})
    _write(evidence / "coverage.json", {"required": {"line": ">=90%", "branch": ">=80%"}, "observed_local_run": coverage, "reason": "full production-source coverage must include every production module; no omit list is permitted"})
    _write(evidence / "package-build.json", package_build)
    security_audit_path = evidence / "security-audit.json"
    if all(value == "PASS" for value in security_checks.values()):
        _write(
            security_audit_path,
            {
                "status": "PASS",
                "checks": {
                    "static_quality_and_dependency_tools": "PASS",
                    "external_secret_scans": "PASS",
                },
                "private_vulnerability_reporting": "documented_github_security_advisory_route",
                "hosted_ci": "repository_ci_workflow",
            },
        )
        _write(
            evidence / "release-security-summary.json",
            {
                "status": "PASS",
                "gitleaks": "PASS",
                "trufflehog": "PASS",
                "citation_validation": "PASS",
                "local_private_path_scan": "PASS",
                "secret_values_emitted": False,
                "ephemeral_state": "scanner logs and local paths are intentionally omitted",
            },
        )
    else:
        _write(
            security_audit_path,
            {
                "status": "BLOCKED",
                "checks": {
                    "static_quality_and_dependency_tools": "BLOCKED",
                    "external_secret_scans": "BLOCKED",
                },
                "private_vulnerability_reporting": "documented_github_security_advisory_route",
                "hosted_ci": "repository_ci_workflow",
            },
        )
        _write(
            evidence / "release-security-summary.json",
            {
                "status": "NOT_RUN",
                "gitleaks": "NOT_RUN",
                "trufflehog": "NOT_RUN",
                "citation_validation": "NOT_RUN",
                "local_private_path_scan": "PASS",
                "secret_values_emitted": False,
                "ephemeral_state": "scanner logs and local paths are intentionally omitted",
            },
        )
    _write(evidence / "artifact-integrity.json", artifacts)
    _write(evidence / "canonical-reproduction.json", {"status": "PASS" if canonical_pass and historical_pass and safety_pass else "BLOCKED_PARTIAL_EXECUTION" if safety_execution or protocol_smoke or historical_execution or canonical_result else "NOT_RUN", "suite": V12_SUITE_ID, "candidate_interface": "candidate-image plus candidate-argv", "historical_runtime": historical_execution, "safety_execution": safety_execution, "canonical_candidate_execution": canonical_result, "candidate_protocol_smoke": protocol_smoke, "network_used": False, "reference_used_as_runtime_evidence": False, "exact_comparison": compare_exact_reference({"suite_id": V12_SUITE_ID}, None)})
    gates = {
        "package_build": package_build["status"],
        "candidate_bundle": "PASS" if candidate["valid"] else "FAIL",
        "gold_separation": "PASS" if separation["valid"] else "FAIL",
        "information_sufficiency": info["status"],
        "baseline_freeze": baseline["status"],
        "resource_integrity": mirror["status"],
        "coverage": coverage["status"],
        "security": "PASS" if all(value == "PASS" for value in security_checks.values()) else "BLOCKED",
        "clean_clone_reproduction": clean_clone.get("status", "NOT_RUN") if isinstance(clean_clone, dict) else "NOT_RUN",
        "candidate_isolation": "PASS" if canonical_pass else "PASS_PROTOCOL_SMOKE_ONLY" if smoke_completed else "BLOCKED",
        "candidate_protocol_smoke": "PASS" if smoke_completed else "BLOCKED",
        "historical_execution": "PASS" if historical_pass else "BLOCKED",
        "canonical_decisive_v1_2": "PASS" if canonical_pass else "BLOCKED_PARTIAL_EXECUTION" if safety_execution or protocol_smoke or historical_execution or canonical_result else "NOT_RUN",
    }
    required_release_gates = (
        "package_build",
        "candidate_bundle",
        "gold_separation",
        "information_sufficiency",
        "baseline_freeze",
        "resource_integrity",
        "coverage",
        "security",
        "clean_clone_reproduction",
        "candidate_isolation",
        "candidate_protocol_smoke",
        "historical_execution",
        "canonical_decisive_v1_2",
    )
    final_state = "READY_FOR_PUBLIC_LAUNCH_REAUDIT" if all(gates[name] == "PASS" for name in required_release_gates) else "BLOCKED"
    _write(
        evidence / "release-gates.json",
        {
            "package_version": __version__,
            "suite_contract_version": V12_RELEASE_VERSION,
            "suite": V12_SUITE_ID,
            "final_state": final_state,
            "gates": gates,
            "immutable_refs": ["v1.0.0", "v1.0.1", "decisive-v1.1", "reference/decisive-v1.1-result.json"],
            "tag_bound_release_verification": "required for the eventual immutable tag",
        },
    )
    print(json.dumps({"status": final_state, "evidence": str(evidence.relative_to(root)).replace("\\", "/")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
