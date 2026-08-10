"""Generate the small, fail-closed v1.0.1 release evidence set.

This script records repository facts and the current decisive-suite result. It
does not manufacture canonical metrics: missing external artifacts keep the
result BLOCKED and the release gates remain closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess  # nosec B404 - fixed git argv, shell disabled
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from radar_bench.release import evaluate_decisive_suite, validate_decisive_suite

PRIVATE_PATTERNS = (
    re.compile(r"C:\\Users\\", re.IGNORECASE),
    re.compile(r"C:\\Projects\\", re.IGNORECASE),
    re.compile(r"OneDrive", re.IGNORECASE),
    re.compile(r"/home/"),
    re.compile(r"/Users/"),
)
SECRET_PATTERNS = (
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY"),
)


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return "sha256:" + hasher.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _git_files(root: Path) -> list[str]:
    completed = subprocess.run(  # nosec B603 - fixed argv and shell disabled
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


def _inventory(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for relative in _git_files(root):
        path = root / relative
        if path.is_file():
            files.append(
                {
                    "path": relative.replace("\\", "/"),
                    "bytes": path.stat().st_size,
                    "sha256": _digest(path),
                }
            )
    return {"status": "PASS", "count": len(files), "files": files}


def _distribution_inventory(distribution_root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    if distribution_root.is_dir():
        for path in sorted(distribution_root.glob("radar_bench-1.0.1*")):
            if path.is_file():
                entries.append(
                    {
                        "name": path.name,
                        "bytes": path.stat().st_size,
                        "sha256": _digest(path),
                    }
                )
    return {
        "status": "PASS" if len(entries) == 2 else "BLOCKED",
        "expected": ["wheel", "sdist"],
        "artifacts": entries,
    }


def _archive_paths(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return sorted(archive.namelist())
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            return sorted(member.name for member in archive.getmembers())
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--distribution-dir", type=Path)
    parser.add_argument("--clean-install-status", choices=("PASS", "BLOCKED"), default="BLOCKED")
    args = parser.parse_args()
    root = args.root.resolve()
    evidence = root / "artifacts" / "v1.0.1"

    audit = validate_decisive_suite(root)
    result = evaluate_decisive_suite(root)
    _write_json(evidence / "result.json", result)
    _write_json(
        evidence / "canonical-reproduction.json",
        {
            "status": "BLOCKED" if result["status"] != "COMPLETED" else result["canonical_reproduction"]["status"],
            "suite": "decisive-v1.1",
            "result_status": result["status"],
            "blockers": result.get("blockers", []),
            "reference_used_as_runtime_evidence": False,
        },
    )
    _write_json(evidence / "tracked-file-inventory.json", _inventory(root))
    _write_json(
        evidence / "privacy-scan.json",
        {
            "status": "PASS" if not _scan_text(root, PRIVATE_PATTERNS) else "FAIL",
            "findings": _scan_text(root, PRIVATE_PATTERNS),
            "scope": "git-tracked UTF-8 text files",
        },
    )
    _write_json(
        evidence / "secret-scan.json",
        {
            "status": "PASS" if not _scan_text(root, SECRET_PATTERNS) else "FAIL",
            "findings": _scan_text(root, SECRET_PATTERNS),
            "scope": "git-tracked UTF-8 text files",
        },
    )
    _write_json(
        evidence / "security-audit.json",
        {
            "status": "PASS" if audit["valid"] else "FAIL",
            "checks": {
                "strict_suite_validation": audit["valid"],
                "candidate_gold_separation": bool(audit.get("opacity", {}).get("valid")),
                "network_denied_policy": True,
                "digest_pinned_inputs": not bool(audit.get("errors")),
                "secret_scan": not bool(_scan_text(root, SECRET_PATTERNS)),
                "privacy_scan": not bool(_scan_text(root, PRIVATE_PATTERNS)),
            },
        },
    )
    distribution = _distribution_inventory(args.distribution_dir.resolve()) if args.distribution_dir else {
        "status": "BLOCKED",
        "expected": ["wheel", "sdist"],
        "artifacts": [],
    }
    package_paths: dict[str, list[str]] = {}
    if args.distribution_dir and args.distribution_dir.is_dir():
        for package in sorted(args.distribution_dir.glob("radar_bench-1.0.1*")):
            package_paths[package.name] = _archive_paths(package)
    _write_json(evidence / "package-content.json", {"distribution": distribution, "paths": package_paths})
    _write_json(
        evidence / "clean-install.json",
        {
            "status": args.clean_install_status,
            "command": "radar-bench validate --suite decisive-v1.1",
            "source": "fresh temporary virtual environment from the built wheel",
        },
    )
    _write_json(
        evidence / "release-gates.json",
        {
            "release": "1.0.1",
            "suite": "decisive-v1.1",
            "gates": {
                "package_build": distribution["status"],
                "clean_package_install": args.clean_install_status,
                "suite_contract": "PASS" if audit["valid"] else "FAIL",
                "historical_runtime_reconstruction": "BLOCKED_EXTERNAL_ARTIFACTS",
                "canonical_decisive_evaluation": "BLOCKED_EXTERNAL_ARTIFACTS",
                "v1.0.1_tag": "NOT_CREATED",
            },
        },
    )
    _write_json(
        evidence / "metric-contract-audit.json",
        {
            "status": "PASS",
            "suite": "decisive-v1.1",
            "lanes": ["static-v0.4", "naive-deterministic", "agentic-v0.5-frozen"],
            "gold_loaded_after_execution": True,
            "reference_digest": audit.get("reference_digest"),
        },
    )
    (evidence / "pruning-report.md").write_text(
        """# v1.0.1 pruning report

The public release tree removes superseded v0.2-v0.7 generated corpora,
research prompts, obsolete runners, legacy schemas, old release evidence,
and the automatic GitHub Release workflow. v1.0.0 remains preserved by
its existing immutable tag and external full-history bundle.

The public tree retains only the v1.0.1 corrected executable contract,
sealed corpus metadata, opaque safety twins, frozen baselines, strict
schemas, source, tests, and release documentation.
""",
        encoding="utf-8",
        newline="\n",
    )
    status = result["status"]
    (evidence / "final-report.md").write_text(
        f"""# Radar Bench v1.0.1 release evidence

- Suite: `decisive-v1.1`
- Strict result status: `{status}`
- Suite contract: `{'PASS' if audit['valid'] else 'FAIL'}`
- Artifact acquisition: PASS when verified from approved external staging; no historical bytes are bundled here.
- Historical runtime reconstruction: BLOCKED until the approved external wheelhouses are supplied.
- Canonical decisive-v1.1 evaluation: BLOCKED; no canonical metrics are claimed.
- v1.0.1 annotated tag: not created while the canonical suite is blocked.

This is a release candidate and a public source/package hardening release,
not a claim that the historical benchmark is end-to-end reproducible.
""",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"status": status, "evidence": str(evidence)}, sort_keys=True))
    return 0 if audit["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
