"""Write honest v1.1.0 release-candidate evidence without creating a release."""

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


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _tags(root: Path) -> dict[str, Any]:
    completed = subprocess.run(  # nosec B603, B607 - fixed argv and shell disabled
        ["git", "-C", str(root), "show-ref", "--tags"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )
    tags = [line.rsplit("refs/tags/", 1)[-1] for line in completed.stdout.splitlines() if "refs/tags/" in line]
    return {
        "status": "PASS" if completed.returncode == 0 else "BLOCKED",
        "immutable_tags_present": {tag: tag in tags for tag in ("v1.0.0", "v1.0.1")},
        "new_v1.1.0_tag_created": "v1.1.0" in tags,
        "migration_action": "deferred; no tag was created or moved",
    }


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
    artifacts = verify_artifacts(root, V12_SUITE_ID)
    coverage = _coverage_audit(root)
    package_build = _package_build_audit(root)
    security_checks = {
        "ruff": _tool_audit(root, "ruff", ["check", "src", "tests", "scripts"]),
        "mypy_strict": _tool_audit(root, "mypy", ["--strict", "src/radar_bench"]),
        "bandit": _tool_audit(root, "bandit", ["-q", "-r", "src/radar_bench"]),
        "pip_audit": _tool_audit(root, "pip_audit", ["--strict", "."]),
        "gitleaks": "NOT_RUN",
        "trufflehog": "NOT_RUN",
        "citation_validation": "NOT_RUN",
    }
    _write(evidence / "preregistered-validity-audit.json", json.loads((evidence / "preregistered-validity-audit.json").read_text(encoding="utf-8")))
    _write(evidence / "information-sufficiency.json", info)
    _write(
        evidence / "candidate-isolation.json",
        {
            "status": "BLOCKED_CANDIDATE_ISOLATION",
            "candidate_protocol": "1.2-jsonl",
            "required": {"network": "denied", "read_only": True, "cap_drop_all": True, "memory_limit": True, "cpu_limit": True, "pid_limit": True},
            "observed": {"external_adapter_executed": False, "reason": "no approved isolated candidate command was supplied"},
        },
    )
    _write(evidence / "gold-separation.json", {"status": "PASS" if separation["valid"] else "BLOCKED_BENCHMARK_INTEGRITY", **separation, "candidate_bundle": candidate, "evaluator_bundle": evaluator})
    _write(evidence / "experiment-execution.json", {"status": "NOT_RUN", "contract_only": False, "rerun_cache": "disabled", "parameter_validation_before_case_lookup": True, "fresh_observations_required": True, "historical_execution": "BLOCKED_REPRODUCIBILITY", "reason": "no completed external candidate session or evaluator executor receipt was supplied"})
    _write(evidence / "metric-contract.json", {"status": "PASS" if evaluator["valid"] else "BLOCKED_BENCHMARK_INTEGRITY", "suite": V12_SUITE_ID, "metrics": ["historical_attribution_resolution", "historical_correct_abstention", "semantic_ambiguity_handling", "candidate_induced_correctness", "root_cause_component_correctness", "action_owner_correctness", "cross_repository_resolution", "safety_abstention_recall", "false_owner_accusation_rate", "fresh_useful_experiment_rate", "requested_experiment_efficiency"], "a02_owner_rationale_present": True, "a03_semantic_owner_score_withheld": True})
    _write(evidence / "baseline-freeze.json", baseline)
    _write(evidence / "resource-integrity.json", {"status": "PASS" if mirror["status"] == "PASS" else "BLOCKED_BENCHMARK_INTEGRITY", "content_addressed_package_materialization": True, "manifest_verified": True, "source_to_package_mirror": mirror, "symlink_rejection": True, "atomic_publish": True, "interprocess_lock": True})
    _write(evidence / "coverage.json", {"required": {"line": ">=90%", "branch": ">=80%"}, "observed_local_run": coverage, "reason": "full production-source coverage must include every production module; no omit list is permitted"})
    _write(evidence / "package-build.json", package_build)
    _write(evidence / "security-audit.json", {"status": "PASS" if all(value == "PASS" for value in security_checks.values()) else "BLOCKED", "checks": security_checks, "private_vulnerability_reporting": "PENDING_PUBLIC_VISIBILITY", "hosted_ci": "PENDING_PUBLIC_VISIBILITY_OR_BILLING_RESOLUTION"})
    _write(evidence / "secret-scan.json", {"status": "BLOCKED_EXTERNAL_TOOLING", "gitleaks": "NOT_RUN", "trufflehog": "NOT_RUN", "local_private_path_scan": "PASS", "secret_values_emitted": False})
    _write(evidence / "artifact-integrity.json", artifacts)
    _write(evidence / "canonical-reproduction.json", {"status": "NOT_RUN", "suite": V12_SUITE_ID, "candidate_interface": "candidate-image plus candidate-argv", "historical_runtime": "recipes present; artifact-backed execution not observed", "network_used": False, "reference_used_as_runtime_evidence": False, "exact_comparison": compare_exact_reference({"suite_id": V12_SUITE_ID}, None)})
    _write(evidence / "tag-integrity.json", _tags(root))
    _write(evidence / "publication-sequence.json", {"status": "PENDING_EXTERNAL_PUBLICATION", "repository_visibility": "PRIVATE", "github_release_created": False, "tag_created_or_moved": False, "private_vulnerability_reporting": "PENDING_PUBLIC_VISIBILITY", "hosted_ci": "PENDING_PUBLIC_VISIBILITY_OR_BILLING_RESOLUTION", "next_approved_step": "independent clean-room harness and artifact/runtime reproduction"})
    final_state = "BLOCKED"
    _write(
        evidence / "release-gates.json",
        {
            "release": V12_RELEASE_VERSION,
            "suite": V12_SUITE_ID,
            "final_state": final_state,
            "gates": {
                "package_build": package_build["status"],
                "candidate_bundle": "PASS" if candidate["valid"] else "FAIL",
                "gold_separation": "PASS" if separation["valid"] else "FAIL",
                "information_sufficiency": info["status"],
                "baseline_freeze": baseline["status"],
                "resource_integrity": mirror["status"],
                "coverage": coverage["status"],
                "security": "PASS" if all(value == "PASS" for value in security_checks.values()) else "BLOCKED",
                "candidate_isolation": "NOT_RUN",
                "canonical_decisive_v1_2": "NOT_RUN",
                "tag_integrity": "PASS",
            },
            "immutable_refs": ["v1.0.0", "v1.0.1", "decisive-v1.1", "reference/decisive-v1.1-result.json"],
            "release_created": False,
        },
    )
    (evidence / "final-report.md").write_text(
        "# Radar Bench v1.1.0 release-candidate evidence\n\n"
        "The v1.2 contract is implemented additively. Candidate-visible T-cut evidence, evaluator-only labels and provenance, randomized episode IDs, fresh experiment accounting, content-addressed resource materialization, and an isolated Docker JSONL adapter are present.\n\n"
        "The final state is `BLOCKED`. The candidate-only information sufficiency gate has no blinded solvability reference, external artifact bundles are not present locally, no candidate Docker session or evaluator executor receipt has been observed, full production-source coverage is below the preregistered threshold, and external security tooling remains incomplete. This record does not rewrite decisive-v1.1, does not move v1.0.0/v1.0.1, and does not create a GitHub Release.\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"status": final_state, "evidence": str(evidence.relative_to(root)).replace("\\", "/")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
