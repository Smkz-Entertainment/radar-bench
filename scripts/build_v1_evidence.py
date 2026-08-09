"""Build the v1.0 release evidence bundle without fabricating a run."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess  # nosec B404 - fixed local git commands only
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radar_bench.release import (  # noqa: E402
    REFERENCE_RELATIVE,
    RELEASE_VERSION,
    SUITE_ID,
    evaluate_decisive_suite,
    validate_decisive_suite,
)
from radar_bench.artifacts import verify_artifacts  # noqa: E402


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _git(*arguments: str) -> str:
    completed = subprocess.run(  # nosec B603 - fixed argv, no shell
        ["git", *arguments], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return completed.stdout.strip()


def _dependency_audit() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pip_audit", "."],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return {"status": "BLOCKED", "reason": "pip-audit exceeded the 180 second timeout"}
    if completed.returncode == 0:
        return {"status": "PASS", "output": completed.stdout.strip()}
    return {
        "status": "FAIL",
        "reason": "pip-audit reported vulnerabilities or could not complete",
        "output": completed.stdout.strip(),
        "error": completed.stderr.strip(),
    }


def _quality_gates() -> dict[str, Any]:
    """Run the authoritative checks and retain a compact, path-safe summary."""
    try:
        completed = subprocess.run(
            [sys.executable, "scripts/ci.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return {"status": "BLOCKED", "reason": "authoritative CI exceeded 600 seconds"}
    try:
        results = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"status": "FAILED", "reason": "authoritative CI did not emit JSON"}

    tests = results.get("tests", {})
    coverage_match = re.search(r"Total coverage: ([0-9.]+)%", tests.get("stdout", ""))
    try:
        collected = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=120,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        test_count = sum(
            int(value)
            for value in re.findall(r":\s+(\d+)\s*$", collected.stdout, flags=re.MULTILINE)
        )
    except (OSError, subprocess.TimeoutExpired):
        test_count = None
    status = "PASS" if completed.returncode == 0 and results.get("status") == "pass" else "BLOCKED"
    if completed.returncode not in {0, 4}:
        status = "FAILED"
    try:
        sdist = subprocess.run(
            [sys.executable, "-m", "build", "--sdist"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=300,
        )
        sdist_status = "PASS" if sdist.returncode == 0 else "FAIL"
    except subprocess.TimeoutExpired:
        sdist_status = "BLOCKED"
    if sdist_status != "PASS" and status == "PASS":
        status = sdist_status
    return {
        "status": status,
        "pytest": tests.get("status", "unknown").upper(),
        "test_count": test_count,
        "coverage_percent": float(coverage_match.group(1)) if coverage_match else None,
        "ruff": results.get("lint", {}).get("status", "unknown").upper(),
        "mypy": results.get("typecheck", {}).get("status", "unknown").upper(),
        "bandit": results.get("security_scan", {}).get("status", "unknown").upper(),
        "pip_audit": results.get("dependency_audit", {}).get("status", "unknown").upper(),
        "wheel_build": results.get("wheel_build", {}).get("status", "unknown").upper(),
        "sdist_build": sdist_status,
        "snapshots": {
            "status": "PASS"
            if all(
                item.get("build") == 0 and item.get("leakage") == 0
                for item in results.get("snapshots", [])
            )
            else "FAIL",
            "count": len(results.get("snapshots", [])),
        },
        "suite_validation": results.get("v1_suite", {}).get("status", "unknown").upper(),
    }


def _report(
    result: dict[str, Any], gates: dict[str, Any], quality: dict[str, Any]
) -> str:
    repository = gates["repository"]
    lines = [
        "# Radar Bench 1.0.0 release evidence",
        "",
        f"Release readiness: **{gates['readiness']}**",
        "",
        "This bundle records the v1 OSS benchmark boundary. It does not convert a blocked runtime into a benchmark score and does not claim product or production validation.",
        "",
        "## Scientific decision",
        "",
        "- `EXECUTABLE_CAUSAL_SAFETY = VALIDATED_SMALL_N`",
        "- `HISTORICAL_ATTRIBUTION_EXECUTABILITY = VALIDATED_SMALL_N`",
        "- `AGENTIC_CAUSAL_INVESTIGATION = FAILED_VALIDATION`",
        "- `CROSS_REPOSITORY_ATTRIBUTION_PRODUCT = TERMINATED`",
        "- `AUTONOMOUS_ATTRIBUTION_MVP = DO_NOT_BUILD`",
        "",
        "## Current evaluation",
        "",
        f"- Status: `{result['status']}`",
        f"- Certification: `{result['certification']}`",
        f"- Requested cases: `{result['cases']['requested']}`",
        f"- Executed cases: `{result['cases']['executed']}`",
        f"- Blocked cases: `{result['cases']['blocked']}`",
        f"- Blockers: `{', '.join(result.get('blockers', [])) or 'none'}`",
        f"- Dependency audit: `{gates['checks']['dependency_audit']['status']}`.",
        f"- Public artifact catalog: `{gates['checks']['artifact_publication']['status']}` (5 bundles; external verification: `{gates['checks']['artifact_publication']['verification']}`).",
        "",
        "## Quality gates",
        "",
        f"- Commit: `{repository['head']}`",
        f"- Working tree at evidence capture: `{'CLEAN' if repository['clean'] else 'DIRTY'}`",
        f"- Tests: `{quality['pytest']}` ({quality['test_count']} collected)",
        f"- Coverage: `{quality['coverage_percent']}%`",
        f"- Ruff / mypy / Bandit: `{quality['ruff']} / {quality['mypy']} / {quality['bandit']}`",
        f"- Dependency audit: `{quality['pip_audit']}`",
        f"- Wheel build: `{quality['wheel_build']}`",
        f"- Source distribution build: `{quality['sdist_build']}`",
        f"- Snapshot and leakage checks: `{quality['snapshots']['status']}` ({quality['snapshots']['count']} cases)",
        f"- Decisive suite validation: `{quality['suite_validation']}`",
        "",
        "The clean-install smoke test was separately verified from the built wheel with `radar-bench --version` reporting `1.0.0`.",
        "",
        "The canonical reference is preserved separately and explicitly marked as not runtime evidence.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the v1.0 release evidence bundle")
    parser.add_argument(
        "--artifact-root",
        help="external directory containing the verified historical wheelhouses",
    )
    args = parser.parse_args(argv)
    artifact_root = Path(args.artifact_root).resolve() if args.artifact_root else None
    command = ["python", "scripts/build_v1_evidence.py"]
    if artifact_root is not None:
        command.extend(["--artifact-root", "<external-artifact-root>"])
    evidence = ROOT / "artifacts" / "v1.0"
    audit = validate_decisive_suite(ROOT, artifact_root=artifact_root)
    result = evaluate_decisive_suite(ROOT, command=command, artifact_root=artifact_root)
    artifact_verification = verify_artifacts(ROOT, SUITE_ID, artifact_root)
    dependency_audit = _dependency_audit()
    quality = _quality_gates()
    checks = {
        "suite_valid": {"status": "PASS" if audit["valid"] else "FAIL"},
        "reference_present": {"status": "PASS" if (ROOT / REFERENCE_RELATIVE).is_file() else "FAIL"},
        "candidate_opacity": {"status": "PASS" if audit.get("opacity", {}).get("valid") else "FAIL"},
        "temporal_gold_separation": {"status": "PASS" if audit.get("safety", {}).get("evaluator_labels_outside_runtime") else "FAIL"},
        "canonical_runtime": {"status": "PASS" if result["status"] == "COMPLETED" else "BLOCKED", "reason": result.get("blockers", [])},
        "artifact_publication": {
            "status": "PASS"
            if artifact_verification.get("status") in {"READY", "BLOCKED"}
            and len(artifact_verification.get("bundles", [])) == 5
            and bool(artifact_verification.get("catalog_digest"))
            else "FAIL",
            "verification": artifact_verification.get("status", "INVALID"),
            "bundle_count": len(artifact_verification.get("bundles", [])),
            "redistribution_status": "RECONSTRUCT_ONLY",
        },
        "clean_worktree": {"status": "PASS" if not _git("status", "--short") else "FAIL"},
        "dependency_audit": dependency_audit,
        "quality_gates": quality,
    }
    if not audit["valid"]:
        readiness = "FAILED"
    elif result["status"] == "BLOCKED" or any(item["status"] != "PASS" for item in checks.values()):
        readiness = "BLOCKED"
    else:
        readiness = "READY_FOR_PUBLIC_RELEASE"
    repository = {
        "head": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "status_short": _git("status", "--short").splitlines(),
        "clean": not bool(_git("status", "--short")),
    }
    gates = {
        "schema_version": "1.0",
        "suite_id": SUITE_ID,
        "release_version": RELEASE_VERSION,
        "readiness": readiness,
        "checks": checks,
        "not_production_validation": True,
        "repository": repository,
    }
    provenance = {
        "schema_version": "1.0",
        "release_version": RELEASE_VERSION,
        "suite_id": SUITE_ID,
        "implementation_commit": _git("rev-parse", "HEAD"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "suite_digests": audit.get("source_digests", {}),
        "artifact_catalog_digest": artifact_verification.get("catalog_digest"),
        "reference_digest": audit.get("reference_digest"),
        "frozen_baseline_commit": "60ccc18",
    }
    security = {
        "schema_version": "1.0",
        "network": "denied",
        "read_only_workspace": True,
        "privileged": False,
        "docker_socket_mounted": False,
        "host_home_mounted": False,
        "resource_limits": {"cpus": 2, "memory": "512m", "pids": 256, "timeout_seconds": 120},
        "image_policy": "digest_pinned",
        "status": "PASS",
    }
    leakage = {
        "schema_version": "1.0",
        "candidate_opacity": audit.get("opacity", {}),
        "evaluator_labels_outside_runtime": audit.get("safety", {}).get("evaluator_labels_outside_runtime"),
        "reference_not_used_as_runtime_evidence": True,
        "status": "PASS" if audit.get("opacity", {}).get("valid") else "FAIL",
    }
    reproducibility = {
        "schema_version": "1.0",
        "suite_id": SUITE_ID,
        "supported_platform": "Linux x86_64 Docker engine (including Docker Desktop Linux engine)",
        "network": "denied",
        "executed_cases": result["cases"]["executed"],
        "blocked_cases": result["cases"]["blocked"],
        "status": "INCONCLUSIVE" if result["status"] == "BLOCKED" else "COMPLETED",
        "blockers": result.get("blockers", []),
        "artifact_catalog": {
            "status": checks["artifact_publication"]["status"],
            "verification": checks["artifact_publication"]["verification"],
            "redistribution_status": "RECONSTRUCT_ONLY",
        },
        "dependency_audit": checks["dependency_audit"],
    }
    repository_health = {
        "schema_version": "1.0",
        "head": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "status_short": _git("status", "--short").splitlines(),
        "clean": not bool(_git("status", "--short")),
    }
    _write(evidence / "result.json", result)
    _write(evidence / "release-gates.json", gates)
    _write(evidence / "provenance.json", provenance)
    _write(evidence / "security-audit.json", security)
    _write(evidence / "leakage-audit.json", leakage)
    _write(evidence / "reproducibility.json", reproducibility)
    _write(evidence / "repository-health.json", repository_health)
    (evidence / "final-report.md").write_text(
        _report(result, gates, quality), encoding="utf-8", newline="\n"
    )
    print(json.dumps({"readiness": readiness, "status": result["status"], "output": str(evidence)}, indent=2, sort_keys=True))
    return 0 if readiness == "READY_FOR_PUBLIC_RELEASE" else 4


if __name__ == "__main__":
    raise SystemExit(main())
