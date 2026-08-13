"""Audit wheel, sdist, evaluator asset, provenance, and checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess  # nosec B404 - fixed git argv and shell disabled
import tarfile
import zipfile
from pathlib import Path
from typing import Any


EVALUATOR_NAME = "radar-bench-decisive-v1.2-evaluator.json"
FORBIDDEN = (
    "/resources/reference/",
    "/resources/baselines/",
    "/resources/evaluator/",
    "/evaluator/decisive-v1.2/",
    "/evaluator-bundle.json/",
    "/evaluator-labels.json/",
    "/safety-twins/views/",
)
REQUIRED_PUBLIC = (
    "/resources/corpus/v1.0.1/decisive-v1.1/reproducers/",
    "/resources/corpus/v1.0.1/safety-twins/runtime/",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_names(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()
    with tarfile.open(path, "r:gz") as archive:
        return archive.getnames()


def _tracked_binary_files(root: Path) -> list[str]:
    completed = subprocess.run(  # nosec B603, B607 - fixed argv and shell disabled
        ["git", "-C", str(root), "ls-files", "--", "*.whl", "*.tar.gz"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )
    return [line for line in completed.stdout.splitlines() if line]


def _git_value(root: Path, *arguments: str) -> str | None:
    completed = subprocess.run(  # nosec B603, B607 - fixed argv and shell disabled
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def audit(dist: Path, root: Path | None = None) -> dict[str, Any]:
    dist = dist.resolve()
    expected = {
        "radar_bench-1.1.1-py3-none-any.whl",
        "radar_bench-1.1.1.tar.gz",
        EVALUATOR_NAME,
        "SOURCE-PROVENANCE.json",
        "SHA256SUMS",
    }
    errors: list[str] = []
    files = {path.name for path in dist.iterdir() if path.is_file()} if dist.is_dir() else set()
    missing = sorted(expected - files)
    extra = sorted(files - expected)
    if missing:
        errors.append(f"missing release assets: {', '.join(missing)}")
    if extra:
        errors.append(f"unexpected release assets: {', '.join(extra)}")
    provenance: dict[str, Any] = {}
    provenance_path = dist / "SOURCE-PROVENANCE.json"
    if provenance_path.is_file():
        try:
            loaded = json.loads(provenance_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                provenance = loaded
            else:
                errors.append("SOURCE-PROVENANCE.json is not an object")
        except (OSError, ValueError) as exc:
            errors.append(f"provenance unreadable: {type(exc).__name__}")
    required_provenance = {
        "release_tag": "v1.1.1",
        "package_version": "1.1.1",
        "suite": "decisive-v1.2",
        "protocol": "1.2-jsonl",
    }
    for key, value in required_provenance.items():
        if provenance.get(key) != value:
            errors.append(f"provenance {key} is not {value!r}")
    if provenance.get("artifacts") != [EVALUATOR_NAME, "radar_bench-1.1.1-py3-none-any.whl", "radar_bench-1.1.1.tar.gz"]:
        errors.append("provenance artifact list is not the exact distributable set")
    checksum_path = dist / "SHA256SUMS"
    if checksum_path.is_file():
        try:
            lines = checksum_path.read_text(encoding="ascii").splitlines()
            expected_hashes = {name: digest for digest, name in (line.split("  ", 1) for line in lines)}
            if set(expected_hashes) != expected - {"SHA256SUMS"}:
                errors.append("checksum manifest does not cover exactly the non-manifest assets")
            for name, digest in expected_hashes.items():
                path = dist / name
                if not path.is_file() or _sha256(path) != digest:
                    errors.append(f"checksum mismatch: {name}")
        except (OSError, ValueError) as exc:
            errors.append(f"checksum manifest unreadable: {type(exc).__name__}")
    else:
        errors.append("SHA256SUMS is absent")
    evaluator_path = dist / EVALUATOR_NAME
    if evaluator_path.is_file():
        try:
            evaluator = json.loads(evaluator_path.read_text(encoding="utf-8"))
            if not isinstance(evaluator, dict) or evaluator.get("suite_id") != "decisive-v1.2" or evaluator.get("bundle_type") != "evaluator-only":
                errors.append("evaluator asset identity is invalid")
            elif len(evaluator.get("record_case_mapping", {})) != 25 or len(evaluator.get("labels", {}).get("cases", {})) != 25 or len(evaluator.get("gold_provenance", [])) != 25:
                errors.append("evaluator asset does not contain exactly 25 mapped, labeled cases and provenance records")
        except (OSError, ValueError) as exc:
            errors.append(f"evaluator asset unreadable: {type(exc).__name__}")
    for name in ("radar_bench-1.1.1-py3-none-any.whl", "radar_bench-1.1.1.tar.gz"):
        archive = dist / name
        if not archive.is_file():
            continue
        lowered = ["/" + item.lower().replace("\\", "/") + "/" for item in _archive_names(archive)]
        if any(any(token in item for token in FORBIDDEN) for item in lowered):
            errors.append(f"{name} contains evaluator/reference material")
        if not all(any(token in item for item in lowered) for token in REQUIRED_PUBLIC):
            errors.append(f"{name} is missing required public runtime fixtures")
        if not any("decisive-v1.2" in item for item in lowered):
            errors.append(f"{name} is missing decisive-v1.2 resources")
    if root is not None:
        resolved_root = root.resolve()
        tracked = _tracked_binary_files(resolved_root)
        if tracked:
            errors.append(f"release binaries are tracked in Git: {', '.join(tracked)}")
        expected_commit = _git_value(resolved_root, "rev-parse", "HEAD")
        expected_tree = _git_value(resolved_root, "rev-parse", "HEAD^{tree}")
        if expected_commit is not None and provenance.get("source_commit") != expected_commit:
            errors.append("provenance source_commit does not match the checked-out commit")
        if expected_tree is not None and provenance.get("source_tree") != expected_tree:
            errors.append("provenance source_tree does not match the checked-out commit tree")
    return {"status": "PASS" if not errors else "FAIL", "files": sorted(files), "provenance": provenance, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    result = audit(args.dist, args.root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
