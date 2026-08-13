"""Materialize the evaluator release asset and provenance/checksum files."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess  # nosec B404 - fixed git argv and shell disabled
import tomllib
from pathlib import Path

from audit_release_assets import EVALUATOR_NAME


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(  # nosec B603, B607 - fixed argv and shell disabled
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        shell=False,
    )
    return completed.stdout.strip()


def prepare(root: Path, dist: Path, release_tag: str) -> dict[str, object]:
    root = root.resolve()
    dist = dist.resolve()
    dist.mkdir(parents=True, exist_ok=True)
    evaluator_source = root / "evaluator" / "decisive-v1.2" / "evaluator-bundle.json"
    if not evaluator_source.is_file():
        raise FileNotFoundError(evaluator_source)
    wheel = dist / "radar_bench-1.1.1-py3-none-any.whl"
    sdist = dist / "radar_bench-1.1.1.tar.gz"
    if not wheel.is_file() or not sdist.is_file():
        raise FileNotFoundError("wheel and sdist must be built before release preparation")
    evaluator_target = dist / EVALUATOR_NAME
    shutil.copyfile(evaluator_source, evaluator_target)
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(project["project"]["version"])
    if version != "1.1.1" or release_tag != "v1.1.1":
        raise ValueError("release assets are fixed to package/tag v1.1.1")
    provenance = {
        "schema_version": "1",
        "release_tag": release_tag,
        "package_version": version,
        "source_commit": _git(root, "rev-parse", "HEAD"),
        "source_tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "suite": "decisive-v1.2",
        "protocol": "1.2-jsonl",
        "artifacts": sorted((wheel.name, sdist.name, evaluator_target.name)),
    }
    (dist / "SOURCE-PROVENANCE.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    files = sorted(path for path in dist.iterdir() if path.is_file())
    checksums = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in files
    )
    (dist / "SHA256SUMS").write_text(checksums, encoding="ascii")
    return provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--release-tag", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.root, args.dist, args.release_tag), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
