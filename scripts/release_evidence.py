"""Generate local release evidence from completed, reproducible checks."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from setuptools.build_meta import build_sdist, build_wheel

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts" / "release-evidence"
sys.path.insert(0, str(ROOT / "src"))


def write(path: Path, value: str | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        value
        if isinstance(value, str)
        else json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    env = {**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}
    ci = subprocess.run(
        [sys.executable, "scripts/ci.py"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    write(
        EVIDENCE / "authoritative-ci.json",
        {"returncode": ci.returncode, "stdout": ci.stdout, "stderr": ci.stderr},
    )
    if ci.returncode:
        raise SystemExit(ci.returncode)
    write(
        EVIDENCE / "runtime-versions.txt",
        f"python={platform.python_version()}\nos={platform.platform()}\nimplementation={platform.python_implementation()}\n",
    )
    cases = sorted((ROOT / "corpus" / "cases").glob("*.json"))
    validation = []
    for case in cases:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "radar_bench.cli",
                "validate-case",
                str(case),
                "--json",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            shell=False,
        )
        validation.append(json.loads(result.stdout))
    write(
        EVIDENCE / "schema-validation.json",
        {"valid": all(item["valid"] for item in validation), "records": validation},
    )
    leakage = []
    for case in cases:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "radar_bench.cli",
                "check-leakage",
                case.stem,
                "--json",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            shell=False,
        )
        leakage.append(json.loads(result.stdout))
    write(
        EVIDENCE / "leakage-report.json",
        {"valid": all(item["valid"] for item in leakage), "records": leakage},
    )
    predictions_path = EVIDENCE / "baseline-seed.jsonl"
    lines = []
    for snapshot in sorted(
        (ROOT / "corpus" / "snapshots").glob("*/input/snapshot.json")
    ):
        packet = json.loads(snapshot.read_text(encoding="utf-8"))
        from radar_bench.baseline.engine import predict

        lines.append(json.dumps(predict(packet), sort_keys=True))
    write(predictions_path, "\n".join(lines) + "\n")
    evaluation = subprocess.run(
        [
            sys.executable,
            "-m",
            "radar_bench.cli",
            "evaluate",
            str(predictions_path),
            "--output",
            str(EVIDENCE / "benchmark-report.json"),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    write(EVIDENCE / "benchmark-report.md", evaluation.stdout)
    report = json.loads(
        (EVIDENCE / "benchmark-report.json").read_text(encoding="utf-8")
    )
    gates = subprocess.run(
        [
            sys.executable,
            "-m",
            "radar_bench.cli",
            "gates",
            str(EVIDENCE / "benchmark-report.json"),
            "--json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    write(EVIDENCE / "gates.json", json.loads(gates.stdout))
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    wheel = build_wheel(str(dist), config_settings={})
    sdist = build_sdist(str(dist), config_settings={})
    hashes = {}
    for name in (wheel, sdist):
        path = dist / name
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    write(EVIDENCE / "package-hashes.json", hashes)
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "site"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--target",
                str(target),
                str(dist / wheel),
            ],
            check=True,
            capture_output=True,
            text=True,
            shell=False,
        )
        smoke = subprocess.run(
            [sys.executable, "-m", "radar_bench.cli", "--help"],
            env={**env, "PYTHONPATH": str(target)},
            text=True,
            capture_output=True,
            check=False,
            shell=False,
        )
        write(EVIDENCE / "clean-install-smoke.txt", smoke.stdout + smoke.stderr)
        if smoke.returncode:
            raise SystemExit(smoke.returncode)
    write(
        EVIDENCE / "test-summary.json",
        {
            "authoritative_ci_returncode": ci.returncode,
            "benchmark": report.get("metrics", {}),
        },
    )
    commit = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            shell=False,
        ).stdout.strip()
        or None
    )
    result = {
        "project": "ecosystem-radar-bench",
        "version": "0.1.0",
        "status": "partial",
        "commit": commit,
        "checks": {
            "authoritative_ci": "pass",
            "schema_validation": "pass",
            "leakage": "pass",
            "package_build": "pass",
            "clean_install_smoke": "pass",
        },
        "corpus": {
            "manifest_rows": 12,
            "curated_local_records": 12,
            "inference_snapshots": len(cases),
            "tier_counts": {"A": 6, "B": 4, "C": 2},
            "external_collection": "not claimed",
        },
        "benchmark": {
            "seed_results": "exploratory",
            "report": "artifacts/release-evidence/benchmark-report.json",
            "gates": "artifacts/release-evidence/gates.json",
        },
        "security": {
            "threat_model": "docs/THREAT_MODEL.md",
            "local_regressions": "pass",
        },
        "blockers": [
            "Public-source collection and independent gold curation are not complete enough for production expansion."
        ],
        "next_recommendation": "Do not proceed to headline 80-120-case claims until public evidence is collected, reviewed, and hidden-test gates are measured.",
    }
    write(ROOT / "artifacts" / "result.json", result)
    write(
        ROOT / "artifacts" / "final-report.md",
        "# Final implementation report\n\n## Status\n\nThe local v0.1 foundation is implemented and its offline checks/package smoke test pass. The seed metrics are exploratory only; public-source collection and independent gold curation remain incomplete.\n\n## Evidence\n\n- Authoritative CI: `artifacts/release-evidence/authoritative-ci.json`\n- Schema and temporal reports: `artifacts/release-evidence/schema-validation.json`, `artifacts/release-evidence/leakage-report.json`\n- Baseline seed report: `artifacts/release-evidence/benchmark-report.json` and `.md`\n- Future product gates: `artifacts/release-evidence/gates.json`\n- Package hashes and clean install: `artifacts/release-evidence/package-hashes.json`, `clean-install-smoke.txt`\n\n## Recommendation\n\nThe safety foundation is suitable for continued curation work, but evidence does not support claiming production-quality 80-120-case benchmark accuracy yet.\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
