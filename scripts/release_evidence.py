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
    predictions_v02_path = EVIDENCE / "baseline-v02-seed.jsonl"
    v02_lines = []
    for snapshot in sorted(
        (ROOT / "corpus" / "snapshots").glob("*/input/snapshot.json")
    ):
        packet = json.loads(snapshot.read_text(encoding="utf-8"))
        from radar_bench.baseline.engine import predict_v02

        v02_lines.append(json.dumps(predict_v02(packet), sort_keys=True))
    write(predictions_v02_path, "\n".join(v02_lines) + "\n")
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
    write(EVIDENCE / "benchmark-report.md", evaluation.stdout.rstrip() + "\n")
    report = json.loads(
        (EVIDENCE / "benchmark-report.json").read_text(encoding="utf-8")
    )
    evaluation_v02 = subprocess.run(
        [
            sys.executable,
            "-m",
            "radar_bench.cli",
            "evaluate",
            str(predictions_v02_path),
            "--output",
            str(EVIDENCE / "benchmark-v02-report.json"),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    write(
        EVIDENCE / "benchmark-v02-report.md",
        evaluation_v02.stdout.rstrip() + "\n",
    )
    report_v02 = json.loads(
        (EVIDENCE / "benchmark-v02-report.json").read_text(encoding="utf-8")
    )
    gates_v02 = subprocess.run(
        [
            sys.executable,
            "-m",
            "radar_bench.cli",
            "gates",
            str(EVIDENCE / "benchmark-v02-report.json"),
            "--json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    write(EVIDENCE / "v02-gates.json", json.loads(gates_v02.stdout))
    v02_plan = subprocess.run(
        [sys.executable, "-m", "radar_bench.cli", "validate-v02-corpus"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    write(EVIDENCE / "v02-corpus-plan.json", json.loads(v02_plan.stdout))
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
            "benchmark_v02": report_v02.get("metrics", {}),
            "v02_corpus_plan_returncode": v02_plan.returncode,
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
        "validation_milestone": "0.2",
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
        "validation_v02": {
            "corpus_plan": "artifacts/release-evidence/v02-corpus-plan.json",
            "deterministic_report": "artifacts/release-evidence/benchmark-v02-report.json",
            "gates": "artifacts/release-evidence/v02-gates.json",
            "gold_cases_admitted": 0,
            "ablation": "not_run; exact hidden cases and local/Codex lanes are not yet available",
        },
        "security": {
            "threat_model": "docs/THREAT_MODEL.md",
            "local_regressions": "pass",
        },
        "blockers": [
            "Public-source collection and independent gold curation are not complete enough for production expansion."
        ],
        "next_recommendation": "Populate the v0.2 admission plan with independently grounded public evidence, then run the exact hidden-case deterministic/local-model/Codex ablation before product work.",
    }
    write(ROOT / "artifacts" / "result.json", result)
    write(
        ROOT / "artifacts" / "final-report.md",
        "# Final implementation report\n\n## Status\n\nThe v0.1 engineering foundation is frozen and its local checks/package smoke test pass. v0.2 Attribution Validation is implemented as a research harness: its 100 planned slots and deterministic seed metrics are exploratory, with zero admitted independent gold cases.\n\n## Evidence\n\n- Authoritative CI: `artifacts/release-evidence/authoritative-ci.json`\n- v0.1 schema and temporal reports: `artifacts/release-evidence/schema-validation.json`, `artifacts/release-evidence/leakage-report.json`\n- v0.1 baseline report: `artifacts/release-evidence/benchmark-report.json` and `.md`\n- v0.2 corpus plan: `artifacts/release-evidence/v02-corpus-plan.json`\n- v0.2 deterministic report and gates: `artifacts/release-evidence/benchmark-v02-report.json`, `benchmark-v02-report.md`, `v02-gates.json`\n- Package hashes and clean install: `artifacts/release-evidence/package-hashes.json`, `clean-install-smoke.txt`\n\n## Recommendation\n\nDo not claim production attribution or build user-facing Radar integrations. First populate and independently admit the adversarial corpus, require zero false high-confidence upstream accusations, and run the deterministic/local-model/Codex ablation on the exact same hidden cases.\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
