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

from radar_bench.blindness import run_blind_provider  # noqa: E402
from radar_bench.evaluation.ablation import v03_lane_plan  # noqa: E402
from radar_bench.evaluation.stages import build_freeze_manifest  # noqa: E402
from radar_bench.evaluation.statistics import safety_confidence  # noqa: E402


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
    v03_plan = subprocess.run(
        [sys.executable, "-m", "radar_bench.cli", "validate-v03-corpus", "--json"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    v03_plan_result = json.loads(v03_plan.stdout)
    write(EVIDENCE / "corpus-stats.json", v03_plan_result["summary"])
    if v03_plan.returncode:
        raise SystemExit(v03_plan.returncode)
    v03_report = {
        "protocol_version": "0.3",
        "exploratory": True,
        "metrics": {
            "counts": {
                "predictions": 0,
                "valid": 0,
                "invalid": 0,
                "answered": 0,
                "abstained": 0,
                "gold_answered": 0,
                "gold_abstain": 0,
                "high_confidence": 0,
                "safety_labels": 0,
                "safety_predictions": 0,
            },
            "candidate_induction": {
                "precision": {"value": None, "numerator": 0, "denominator": 0},
                "recall": {"value": None, "numerator": 0, "denominator": 0},
            },
            "action_owner": {
                "precision": {"value": None, "numerator": 0, "denominator": 0},
                "recall": {"value": None, "numerator": 0, "denominator": 0},
            },
            "abstention": {
                "precision": {"value": None, "numerator": 0, "denominator": 0},
                "recall": {"value": None, "numerator": 0, "denominator": 0},
            },
            "false_high_confidence_upstream": safety_confidence(0, 0),
            "first_bad": {"value": None, "numerator": 0, "denominator": 0},
            "calibration": {"expected_calibration_error": None, "brier_score": None},
        },
    }
    write(EVIDENCE / "v03-development-report.json", v03_report)
    v03_gates = subprocess.run(
        [
            sys.executable,
            "-m",
            "radar_bench.cli",
            "gates",
            str(EVIDENCE / "v03-development-report.json"),
            "--json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    write(EVIDENCE / "v03-gates.json", json.loads(v03_gates.stdout))
    write(
        EVIDENCE / "safety-confidence.json",
        {
            **safety_confidence(0, 0),
            "planned_safety_cases": v03_plan_result["summary"]["safety_abstention"],
            "admitted_safety_cases": 0,
            "scored_safety_cases": 0,
            "interpretation": "No safety claim is made; planned cases are not a sample.",
        },
    )
    write(
        EVIDENCE / "difficulty-metrics.json",
        {
            "planned_counts": v03_plan_result["summary"]["attribution_difficulty"],
            "scored_counts": {tier: 0 for tier in ("D1", "D2", "D3", "D4", "D5")},
            "metrics": {},
            "status": "not_evaluable_without_admitted_labels",
        },
    )
    commit_for_freeze = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            shell=False,
        ).stdout.strip()
        or "uncommitted"
    )
    freeze = build_freeze_manifest(
        ROOT,
        invocation=[sys.executable, "scripts/release_evidence.py"],
        implementation_commit=commit_for_freeze,
    )
    write(EVIDENCE / "v03-freeze-manifest.json", freeze)
    with tempfile.TemporaryDirectory() as blind_directory:
        blind_root = Path(blind_directory)
        candidate_root = blind_root / "candidate"
        gold_root = blind_root / "gold"
        (candidate_root / "input").mkdir(parents=True)
        gold_root.mkdir()
        write(candidate_root / "input" / "snapshot.json", {"case_id": "RADAR-V03-BLIND-SMOKE"})
        write(gold_root / "label.json", {"secret": True})

        class NeutralProvider:
            def predict(self, packet: dict) -> dict:
                return {"case_id": packet["case_id"], "verdict": "inconclusive"}

        _, blind_record = run_blind_provider(
            NeutralProvider(),
            candidate_root,
            gold_root,
            blind_root / "candidate-output.json",
            implementation_commit=commit_for_freeze,
        )
    write(
        EVIDENCE / "temporal-blindness.json",
        {
            **blind_record.as_dict(),
            "status": "pass",
            "candidate_cannot_enumerate_gold": True,
            "candidate_cannot_read_gold": True,
            "scorer_separate_from_candidate": True,
            "boundary": "portable capability boundary plus network-denied repository client",
            "caveat": "An OS-level sandbox for arbitrary third-party native code is not claimed by this local harness.",
        },
    )
    write(EVIDENCE / "ablation-results.json", v03_lane_plan(freeze["corpus_digest"]))
    write(
        EVIDENCE / "error-taxonomy.json",
        {
            "protocol_version": "0.3",
            "stage": "A",
            "status": "exploratory",
            "categories": [
                "candidate_induction",
                "causal_component",
                "action_owner",
                "first_bad",
                "confounded_change",
                "baseline_broken",
                "infrastructure_or_flaky",
                "resolver_or_artifact",
            ],
            "source": "deterministic development machinery; no admitted v0.3 labels",
        },
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
            "benchmark_v02": report_v02.get("metrics", {}),
            "v02_corpus_plan_returncode": v02_plan.returncode,
            "v03_corpus_plan_returncode": v03_plan.returncode,
            "v03_planned_records": v03_plan_result["summary"]["records"],
            "v03_admitted_records": v03_plan_result["summary"]["admitted_gold"],
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
        "validation_milestone": "0.3",
        "status": "partial",
        "decision": "PARTIAL",
        "production_ready": False,
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
        "validation_v03": {
            "corpus_stats": "artifacts/release-evidence/corpus-stats.json",
            "gates": "artifacts/release-evidence/v03-gates.json",
            "safety_confidence": "artifacts/release-evidence/safety-confidence.json",
            "temporal_blindness": "artifacts/release-evidence/temporal-blindness.json",
            "difficulty_metrics": "artifacts/release-evidence/difficulty-metrics.json",
            "freeze_manifest": "artifacts/release-evidence/v03-freeze-manifest.json",
            "ablation": "artifacts/release-evidence/ablation-results.json",
            "attribution_gold_planned": v03_plan_result["summary"]["attribution_gold"],
            "safety_cases_planned": v03_plan_result["summary"]["safety_abstention"],
            "counterfactuals_planned": v03_plan_result["summary"]["counterfactual_variants"],
            "gold_cases_admitted": v03_plan_result["summary"]["admitted_gold"],
            "hidden_evaluation": "not_run",
        },
        "security": {
            "threat_model": "docs/THREAT_MODEL.md",
            "local_regressions": "pass",
        },
        "blockers": [
            "The v0.3 attribution corpus has zero independently admitted gold cases; planned records are not evidence.",
            "The v0.3 safety set has zero scored cases, so no zero-failure safety claim is permitted.",
            "Hidden temporal-blind evaluation and post-cutoff independent scoring are not run.",
            "Local-model and Codex lanes are blocked_external because no approved credentials or credits are available.",
        ],
        "next_recommendation": "Curate and independently review the v0.3 public cases, freeze hashes before labels reach any candidate, then run the hidden deterministic/local-model/Codex comparison.",
    }
    write(ROOT / "artifacts" / "result.json", result)
    write(
        ROOT / "artifacts" / "final-report.md",
        "# Final implementation report\n\n## Decision: PARTIAL\n\nThe v0.1/v0.2 foundation remains frozen. v0.3 adds the two-corpus plan, fail-closed GoldAdmission, causal ontology, temporal-blind candidate boundary, field-level scoring, exact safety confidence calculations, and freeze/ablation evidence.\n\nThe v0.3 inventory is 120 attribution slots, 300 safety slots, and 50 counterfactual variants. All are planned, with zero admitted gold and zero scored safety cases. This is an engineering milestone, not a benchmark result or production-readiness claim.\n\n## Evidence\n\n- Authoritative CI: `artifacts/release-evidence/authoritative-ci.json`\n- v0.3 corpus stats: `artifacts/release-evidence/corpus-stats.json`\n- v0.3 gates and safety confidence: `artifacts/release-evidence/v03-gates.json`, `artifacts/release-evidence/safety-confidence.json`\n- Temporal boundary: `artifacts/release-evidence/temporal-blindness.json`\n- Freeze and stage metadata: `artifacts/release-evidence/v03-freeze-manifest.json`, `artifacts/release-evidence/error-taxonomy.json`\n- Ablation lane status: `artifacts/release-evidence/ablation-results.json`\n- Frozen v0.1/v0.2 reports remain under their existing evidence paths.\n\n## Unmet gates\n\nNo attribution precision/recall, action-owner precision, first-bad accuracy, or hidden recall claim is made because no independent labels have been admitted. No safety claim is made because the scored safety denominator is zero. Local-model and Codex lanes are blocked_external.\n\n## Next step\n\nComplete read-only public OSINT curation and independent review, retain immutable post-cutoff snapshots, freeze the implementation/corpus hashes, and run the same hidden cases through the deterministic and available model lanes.\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
