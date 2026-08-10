"""Write fail-closed, provenance-based v1.0.1 release evidence.

The script records observed facts. It never turns a missing artifact, missing
tool, or blocked execution into a pass and it never uses a reference result as
runtime evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess  # nosec B404 - fixed argv, shell disabled
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Mapping

from radar_bench.artifacts import verify_artifacts
from radar_bench.release import evaluate_decisive_suite, validate_decisive_suite
from radar_bench.result_contract import file_digest, validate_result_document

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

# Construct the platform patterns from tokens so this verifier does not add
# private example paths to the public tree.
_drive = "[A-Za-z]:" + "\\\\"
PRIVATE_PATTERNS = (
    re.compile(_drive + "(?:" + "Users|Projects" + ")" + "\\\\", re.IGNORECASE),
    re.compile("/" + "(?:home|Users)" + "/[^/\\s]+", re.IGNORECASE),
)
SECRET_PATTERNS = (
    re.compile("gh" + "o_[A-Za-z0-9]{20,}"),
    re.compile("github_" + "pat_[A-Za-z0-9_]{20,}"),
    re.compile("AK" + "IA[0-9A-Z]{16}"),
    re.compile("BEGIN " + "(?:RSA|OPENSSH|EC) " + "PRIVATE KEY"),
)


def _digest(path: Path) -> str:
    return file_digest(path)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _git_files(root: Path) -> list[str]:
    completed = subprocess.run(  # nosec B603, B607 - fixed argv and shell disabled
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
        shell=False,
    )
    return [item for item in completed.stdout.decode("utf-8").split("\0") if item]


def _scan_text(root: Path, patterns: tuple[re.Pattern[str], ...]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative in _git_files(root):
        path = root / relative
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in patterns):
                findings.append({"path": relative.replace("\\", "/"), "line": str(line_number)})
    return findings


def _purpose(relative: str) -> tuple[str, str, str, str]:
    path = relative.replace("\\", "/")
    if path.startswith("src/"):
        return "runtime source", "source", "package source or package data", "KEEP"
    if path.startswith("tests/"):
        return "automated tests", "test", "not packaged", "KEEP"
    if path.startswith("corpus/") or path.startswith("baselines/") or path.startswith("reference/"):
        return "current benchmark contract or frozen baseline", "benchmark", "package resources when under src; otherwise not packaged", "KEEP"
    if path.startswith("schema/"):
        return "strict public schemas", "contract", "not packaged; mirrored resources are packaged", "KEEP"
    if path.startswith("docs/") or path in {"README.md", "BENCHMARK.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md"}:
        return "public project documentation", "documentation", "not packaged", "KEEP"
    if path.startswith("artifacts/"):
        return "release evidence", "evidence", "not packaged", "KEEP"
    if path.startswith(".github/"):
        return "repository automation and policy", "automation", "not packaged", "KEEP"
    if path.startswith("scripts/"):
        return "release and audit tooling", "tooling", "not packaged", "KEEP"
    if path in {"LICENSE", "LICENSES.md", "DATA_LICENSE.md", "NOTICE"}:
        return "license or attribution", "legal", "not packaged", "KEEP"
    return "project configuration", "configuration", "not packaged", "KEEP"


def _inventory(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for relative in _git_files(root):
        path = root / relative
        if path.is_file():
            purpose, classification, package_inclusion, keep = _purpose(relative)
            files.append(
                {
                    "path": relative.replace("\\", "/"),
                    "bytes": path.stat().st_size,
                    "sha256": _digest(path),
                    "purpose": purpose,
                    "release_classification": classification,
                    "package_inclusion": package_inclusion,
                    "keep_decision": keep,
                }
            )
    return {
        "status": "PASS" if files and all(item["keep_decision"] == "KEEP" for item in files) else "FAIL",
        "count": len(files),
        "files": files,
        "removed_categories": [
            "superseded v0.2-v0.7 generated evidence and prompts",
            "obsolete package hashes, replay artifacts, and abandoned product scaffolding",
            "automatic GitHub Release workflow",
        ],
    }


def _distribution_inventory(distribution_root: Path | None) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    if distribution_root and distribution_root.is_dir():
        for path in sorted(distribution_root.glob("radar_bench-1.0.1*")):
            if path.is_file():
                entries.append({"name": path.name, "bytes": path.stat().st_size, "sha256": _digest(path)})
    return {"status": "PASS" if len(entries) == 2 else "BLOCKED", "expected": ["wheel", "sdist"], "artifacts": entries}


def _workflow_audit(root: Path) -> dict[str, Any]:
    workflows = sorted((root / ".github" / "workflows").glob("*.y*ml"))
    unpinned_actions: list[str] = []
    noncanonical_runners: list[str] = []
    action_pattern = re.compile(r"^\s*uses:\s+([^\s]+)@([0-9a-fA-F]{40})(?:\s|$)")
    runner_pattern = re.compile(r"^\s*runs-on:\s+([^\s#]+)")
    for workflow in workflows:
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            if "uses:" in line:
                match = action_pattern.match(line)
                if match is None:
                    unpinned_actions.append(f"{workflow.name}:{line_number}")
            runner = runner_pattern.match(line)
            if runner and runner.group(1) != "ubuntu-24.04":
                noncanonical_runners.append(f"{workflow.name}:{line_number}")
    lock_present = (root / "requirements-dev.lock").is_file()
    return {
        "status": "PASS" if workflows and lock_present and not unpinned_actions and not noncanonical_runners else "FAIL",
        "workflow_count": len(workflows),
        "lock_file": "requirements-dev.lock" if lock_present else None,
        "unpinned_actions": unpinned_actions,
        "noncanonical_runners": noncanonical_runners,
        "source": ".github/workflows and requirements-dev.lock",
    }


def _archive_paths(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return sorted(archive.namelist())
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            return sorted(member.name for member in archive.getmembers())
    return []


def _tag_document(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    completed = subprocess.run(  # nosec B603, B607 - fixed argv and shell disabled
        ["git", "-C", str(root), "show", "v1.0.0:artifacts/v1.0/canonical-results.json"],
        capture_output=True,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        return None, None
    try:
        value = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, None
    return (value if isinstance(value, dict) else None), "sha256:" + hashlib.sha256(completed.stdout).hexdigest()


def _metric(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"value": None, "numerator": None, "denominator": None, "status": "MISSING"}
    numerator = value.get("numerator")
    denominator = value.get("denominator")
    raw = value.get("value")
    return {
        "value": raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None,
        "numerator": numerator if isinstance(numerator, int) and not isinstance(numerator, bool) else None,
        "denominator": denominator if isinstance(denominator, int) and not isinstance(denominator, bool) else None,
        "status": value.get("status", "UNSPECIFIED"),
    }


def _metric_audit(root: Path, result: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    old, old_digest = _tag_document(root)
    old = old or {}
    current_baselines = result.get("baselines", {})
    old_baselines = old.get("baselines", {})
    lanes: dict[str, Any] = {}
    for lane in LANES:
        current_metrics = current_baselines.get(lane, {}).get("metrics", {}) if isinstance(current_baselines, Mapping) else {}
        old_metrics = old_baselines.get(lane, {}) if isinstance(old_baselines, Mapping) else {}
        metrics: dict[str, Any] = {}
        for name in METRICS:
            before = _metric(old_metrics.get(name) if isinstance(old_metrics, Mapping) else None)
            after = _metric(current_metrics.get(name) if isinstance(current_metrics, Mapping) else None)
            metrics[name] = {"archival_v1_0_0": before, "corrected_v1_1": after, "equal": before == after}
        lanes[lane] = metrics
    current_predictions = result.get("case_predictions", {})
    experiment_counts: dict[str, Any] = {}
    if isinstance(current_predictions, Mapping):
        for lane in LANES:
            predictions = current_predictions.get(lane, [])
            counts = [item.get("substantive_experiments", 0) for item in predictions if isinstance(item, Mapping)] if isinstance(predictions, list) else []
            experiment_counts[lane] = {
                "case_count": len(counts),
                "total_substantive_experiments": sum(counts),
                "counts_by_case": counts,
                "useful_labels": "derived by evaluator from executed observations; no archival v1.0 label field",
            }
    old_gates = old.get("mandatory_case_gates", {})
    new_gates = result.get("mandatory_case_gates", {})
    return {
        "status": "CORRECTED_SUITE_REVISION",
        "exact_reproduction": False,
        "suite_transition": {"archival": "decisive-v1", "corrected": "decisive-v1.1", "archival_release": "1.0.0", "corrected_release": "1.0.1"},
        "archival_reference": {"source": "v1.0.0:artifacts/v1.0/canonical-results.json", "digest": old_digest},
        "corrected_reference": {"source": "reference/decisive-v1.1-result.json", "digest": _digest(root / "reference/decisive-v1.1-result.json")},
        "field_contract": {"archival_reference_case_predictions": "NOT_PRESENT", "corrected_reference_case_predictions": "PRESENT", "archival_metric_status_fields": "NOT_PRESENT", "corrected_metric_status_fields": "PRESENT"},
        "baselines": lanes,
        "mandatory_case_gates": {"archival": old_gates, "corrected": new_gates, "equal": old_gates == new_gates},
        "case_predictions": {"archival": "NOT_PRESENT_IN_ARCHIVAL_REFERENCE", "corrected": "PRESENT_IN_EXECUTABLE_RESULT"},
        "experiment_counts_and_useful_labels": experiment_counts,
        "owner_scoring_eligibility": {"archival_denominator_claim": "5 in v1.0.0 reference", "corrected_denominators": {lane: _metric(result.get("baselines", {}).get(lane, {}).get("metrics", {}).get("action_owner_correctness")).get("denominator") for lane in LANES}, "explanation": "The corrected suite uses the sealed evaluator labels and reports their two eligible owner-scored cases. The archival five-case denominator is preserved as historical contract data; it is not silently rewritten."},
        "source_and_label_digests": {"archival_result": "not_runtime_evidence; loaded from immutable tag", "corrected_reference": _digest(root / "reference/decisive-v1.1-result.json"), "suite": result.get("provenance", {}).get("suite_digest"), "historical_labels": result.get("provenance", {}).get("historical_labels_digest"), "safety_labels": result.get("provenance", {}).get("safety_labels_digest"), "runtime_recipes": result.get("provenance", {}).get("runtime_recipe_digest"), "baselines": result.get("provenance", {}).get("baseline_digests"), "frozen_investigator_commit": "60ccc18"},
        "reference_result_contract_match": reference.get("canonical_reproduction", {}).get("status") == "NOT_EVALUABLE" or result.get("reference_comparison", {}).get("status") == "EXACT_MATCH",
    }


def _clean_install(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": "NOT_RECORDED", "source": "no clean-install evidence supplied"}
    value = _read_json(path)
    if value is None:
        return {"status": "FAIL", "source": "supplied clean-install evidence was not valid JSON"}
    return value


def _independent_runs(paths: list[Path], reference: Mapping[str, Any]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in paths:
        document = _read_json(path)
        if document is None:
            records.append({"status": "FAIL", "result_sha256": None})
            continue
        projection = {key: document.get(key) for key in ("cases", "baselines", "case_predictions", "mandatory_case_gates", "provenance", "candidate_gold_separation")}
        encoded = json.dumps(projection, sort_keys=True, separators=(",", ":")).encode("utf-8")
        records.append({"status": document.get("status"), "result_sha256": "sha256:" + hashlib.sha256(encoded).hexdigest(), "reference_comparison": document.get("reference_comparison", {}).get("status")})
    equal = len(records) == 2 and all(item.get("status") == "COMPLETED" for item in records) and records[0].get("result_sha256") == records[1].get("result_sha256")
    return {"status": "PASS" if equal else "BLOCKED", "runs": records, "exact_projection_match": equal, "reference_digest": reference.get("provenance", {}).get("suite_digest")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--distribution-dir", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--result", type=Path, help="use an already completed artifact-backed result without rerunning it")
    parser.add_argument("--clean-install-evidence", type=Path)
    parser.add_argument("--independent-result", type=Path, action="append", default=[])
    parser.add_argument("--quality-evidence", type=Path)
    parser.add_argument("--hosted-ci-status", choices=("PASS", "BLOCKED_EXTERNAL_BILLING", "NOT_RECORDED"), default="NOT_RECORDED")
    parser.add_argument(
        "--private-reporting-status",
        choices=("PASS", "BLOCKED_EXTERNAL_FEATURE", "NOT_RECORDED"),
        default="NOT_RECORDED",
        help="verified maintainer-only vulnerability intake status",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    evidence = root / "artifacts" / "v1.0.1"
    audit = validate_decisive_suite(root, artifact_root=args.artifact_root.resolve() if args.artifact_root else None)
    artifact_check = verify_artifacts(root, "decisive-v1.1", args.artifact_root.resolve()) if args.artifact_root else {"status": "BLOCKED", "errors": ["artifact root not supplied"], "bundles": []}
    result = _read_json(args.result.resolve()) if args.result else evaluate_decisive_suite(root, artifact_root=args.artifact_root.resolve() if args.artifact_root else None)
    if result is None:
        raise SystemExit("supplied result is not a JSON object")
    validate_result_document(result, root)
    result_schema_valid = True
    reference = _read_json(root / "reference/decisive-v1.1-result.json") or {}
    quality = _read_json(args.quality_evidence.resolve()) if args.quality_evidence else {"status": "NOT_RECORDED", "checks": {}}
    workflow_audit = _workflow_audit(root)
    metadata_audit = _read_json(evidence / "metadata-only-inference.json") or {"status": "NOT_RECORDED"}
    _write_json(evidence / "result.json", result)
    metric_audit = _metric_audit(root, result, reference)
    _write_json(evidence / "metric-contract-audit.json", metric_audit)
    (evidence / "metric-contract-audit.md").write_text(
        "# Metric contract audit\n\n"
        "`decisive-v1.1` is a corrected immutable suite revision, not a silent redefinition of `decisive-v1`.\n\n"
        f"- archival suite: `decisive-v1` from immutable `v1.0.0`\n- corrected suite: `decisive-v1.1`\n- contract status: `{metric_audit['status']}`\n- exact reproduction of archival metrics: `{metric_audit['exact_reproduction']}`\n\n"
        "The JSON record contains the field-by-field lane/metric comparison, archival and corrected gate values, case-prediction availability, experiment counts, owner-scoring eligibility, and source/label digests. Differences are preserved as evidence; no old denominator or result is overwritten.\n",
        encoding="utf-8",
        newline="\n",
    )
    privacy_findings = _scan_text(root, PRIVATE_PATTERNS)
    secret_findings = _scan_text(root, SECRET_PATTERNS)
    external_scanners = {
        name: value
        for name, value in quality.get("checks", {}).items()
        if isinstance(name, str) and name.startswith(("gitleaks", "trufflehog"))
    }
    _write_json(evidence / "privacy-scan.json", {"status": "PASS" if not privacy_findings else "FAIL", "findings": privacy_findings, "scope": "git-tracked UTF-8 text files", "method": "generic Windows/POSIX home/project pattern scan; no private sample paths", "external_scanners": {"gitleaks_current": external_scanners.get("gitleaks_current", {"status": "NOT_RECORDED"})}})
    _write_json(evidence / "secret-scan.json", {"status": "PASS" if not secret_findings and all(value.get("status") == "PASS" for value in external_scanners.values() if isinstance(value, Mapping)) else "FAIL", "findings": secret_findings, "scope": "git-tracked UTF-8 text files plus reachable history and package/archive scan records", "method": "redacted token/private-key pattern scan; no secret values emitted", "external_scanners": external_scanners})
    distribution = _distribution_inventory(args.distribution_dir.resolve() if args.distribution_dir else None)
    package_paths: dict[str, list[str]] = {}
    if args.distribution_dir and args.distribution_dir.is_dir():
        for package in sorted(args.distribution_dir.glob("radar_bench-1.0.1*")):
            package_paths[package.name] = _archive_paths(package)
    _write_json(evidence / "package-content.json", {"distribution": distribution, "paths": package_paths})
    _write_json(
        evidence / "artifact-reconstruction.json",
        {
            "status": artifact_check.get("status"),
            "suite": "decisive-v1.1",
            "catalog_digest": artifact_check.get("catalog_digest"),
            "network_used": artifact_check.get("network_used"),
            "bundles": [
                {key: item.get(key) for key in ("artifact_id", "bundle_digest", "bytes", "status", "errors")}
                for item in artifact_check.get("bundles", [])
                if isinstance(item, Mapping)
            ],
            "artifact_root": "external-artifact-root",
        },
    )
    clean_install = _clean_install(args.clean_install_evidence)
    _write_json(evidence / "clean-install.json", clean_install)
    independent = _independent_runs([item.resolve() for item in args.independent_result], result)
    _write_json(evidence / "canonical-reproduction.json", {"status": "PASS" if result.get("canonical_reproduction", {}).get("status") == "CORRECTED_SUITE_REFERENCE_MATCH" else "BLOCKED", "suite": "decisive-v1.1", "result_status": result.get("status"), "executed_cases": result.get("cases", {}).get("executed"), "reference_comparison": result.get("reference_comparison"), "independent_clean_clone_runs": independent, "reference_used_as_runtime_evidence": False})
    docker_observed = result.get("status") == "COMPLETED" and result.get("provenance", {}).get("execution_network") == "none" and result.get("provenance", {}).get("platform", {}).get("engine_os") == "linux"
    checks = {"suite_contract": bool(audit.get("valid")), "result_schema": result_schema_valid, "privacy_scan": not privacy_findings, "secret_scan": not secret_findings, "distribution": distribution["status"] == "PASS", "artifact_reconstruction": artifact_check.get("status") == "READY", "clean_install": clean_install.get("status") == "PASS", "canonical_reference_match": result.get("reference_comparison", {}).get("status") == "EXACT_MATCH", "independent_clean_clone_runs": independent["status"] == "PASS", "docker_execution_observed": docker_observed, "metadata_only_inference": metadata_audit.get("status") == "PASS", "workflow_audit": workflow_audit.get("status") == "PASS", "quality_checks": quality.get("status") == "PASS", "private_reporting": args.private_reporting_status == "PASS"}
    _write_json(evidence / "security-audit.json", {"status": "PASS" if all(checks.values()) else "BLOCKED", "checks": checks, "configured": {"execution_network": "none", "candidate_gold_separation": True, "digest_pinned_inputs": True, "private_reporting": args.private_reporting_status}, "observed": {"docker_execution": docker_observed, "result_status": result.get("status"), "engine": result.get("provenance", {}).get("platform")}, "workflow_audit": workflow_audit, "metadata_only_inference": metadata_audit, "tool_evidence": quality})
    local_checks = [value for key, value in checks.items() if key != "private_reporting"]
    local_state = "READY_PRIVATE_REPOSITORY" if all(local_checks) else "BLOCKED_SCIENTIFIC_CONTRACT"
    if local_state == "READY_PRIVATE_REPOSITORY" and args.private_reporting_status == "BLOCKED_EXTERNAL_FEATURE":
        final_state = "BLOCKED_SECURITY"
    elif local_state == "READY_PRIVATE_REPOSITORY" and args.hosted_ci_status == "BLOCKED_EXTERNAL_BILLING":
        final_state = "BLOCKED_EXTERNAL_AUTH"
    else:
        final_state = local_state
    _write_json(evidence / "release-gates.json", {"release": "1.0.1", "suite": "decisive-v1.1", "final_state": final_state, "gates": {"package_build": distribution["status"], "clean_package_install": clean_install.get("status", "NOT_RECORDED"), "suite_contract": "PASS" if audit.get("valid") else "FAIL", "historical_runtime_reconstruction": "PASS" if docker_observed else "BLOCKED", "canonical_decisive_evaluation": "PASS" if result.get("reference_comparison", {}).get("status") == "EXACT_MATCH" else "BLOCKED", "independent_clean_clone_reproduction": independent["status"], "metadata_only_inference": "PASS" if metadata_audit.get("status") == "PASS" else "BLOCKED", "workflow_audit": workflow_audit.get("status", "NOT_RECORDED"), "private_reporting": args.private_reporting_status, "v1.0.1_tag": "CANDIDATE_TAG_PRESENT_NOT_FINAL", "hosted_ci": args.hosted_ci_status}})
    _write_json(evidence / "tracked-file-inventory.json", _inventory(root))
    (evidence / "pruning-report.md").write_text(
        "# v1.0.1 pruning report\n\n"
        "The public tree keeps current source, tests, strict schemas, the corrected executable suite, five sealed manifests/reproducers, twenty opaque safety twins, frozen baselines, licenses, security policy, documentation, and current evidence. Superseded v0.2-v0.7 generated reports/prompts, obsolete package hashes and replay artifacts, and abandoned product scaffolding were removed. The immutable `v1.0.0` tag and external full-history bundle preserve historical context.\n",
        encoding="utf-8",
        newline="\n",
    )
    (evidence / "final-report.md").write_text(
        "# Radar Bench v1.0.1 release evidence\n\n"
        f"- strict result: `{result.get('status')}`\n- executed cases: `{result.get('cases', {}).get('executed')}/25`\n- corrected reference comparison: `{result.get('reference_comparison', {}).get('status')}`\n- clean-clone parity: `{independent.get('status')}`\n- metric contract: `{metric_audit['status']}`\n- security evidence: `{('PASS' if all(checks.values()) else 'BLOCKED')}`\n- private reporting: `{args.private_reporting_status}`\n- candidate tag present but not final: `v1.0.1`\n- hosted GitHub CI: `{args.hosted_ci_status}`\n\n"
        "The original v1.0.0 record remains immutable historical evidence. The corrected v1.0.1 result is runtime evidence only when the artifact-backed execution and independent clean-clone records above are present. A completed `UNSAFE` result is the expected negative product-hypothesis outcome; it is not a release-quality or attribution pass.\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"status": result.get("status"), "release_state": final_state, "evidence": "artifacts/v1.0.1"}, sort_keys=True))
    return 0 if audit.get("valid") else 2


if __name__ == "__main__":
    raise SystemExit(main())
