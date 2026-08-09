"""Run the v0.6 Benchmark Integrity Challenge against frozen v0.5."""

from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any, cast

from radar_bench.evaluation.stages import digest_tree
from radar_bench.evaluation.v05 import safety_results
from radar_bench.integrity.v06 import (
    REQUIRED_V06_ARTIFACTS,
    action_space_audit,
    anti_oracle_baselines,
    counterfactual_audit,
    decoy_audit,
    grouped_holdout_audit,
    investigator_freeze_audit,
    metadata_channel_audit,
    real_execution_audit,
    replay_concordance_audit,
    v06_gates,
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts" / "release-evidence"
V05_EVIDENCE = EVIDENCE / "investigation-episodes.json"


def _read(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _implementation_digest() -> str:
    return digest_tree(
        ROOT,
        (
            "src/radar_bench/integrity/*.py",
            "scripts/run_v06_integrity.py",
        ),
    )


def _report(result: dict[str, Any], gates: dict[str, Any], findings: list[str]) -> str:
    lines = [
        "# Radar Bench v0.6 Benchmark Integrity Challenge",
        "",
        "v0.6 attacks the benchmark channel while keeping the v0.5 investigator and v0.4 corpus frozen. It is not a product implementation phase.",
        "",
        "## Decision",
        "",
        f"- Benchmark integrity: `{result['statuses']['V06_BENCHMARK_INTEGRITY']}`.",
        f"- v0.5 investigator: `{result['statuses']['V05_INVESTIGATOR']}`.",
        f"- Product implementation: `{result['statuses']['PRODUCT_IMPLEMENTATION']}`.",
        f"- Decision: `{result['decision']}`.",
        "",
        "## Gate findings",
        "",
    ]
    lines.extend(
        f"- `{name}`: `{item['status']}` (value `{item['value']}`, threshold `{item['threshold']}`)."
        for name, item in gates["checks"].items()
    )
    lines.extend(["", "## Findings", ""])
    lines.extend(f"- {finding}" for finding in findings)
    lines.extend(
        [
            "",
            "The v0.5 investigator was not tuned or modified. The replay oracle's direct result behavior and decoy behavior are treated as benchmark-integrity findings, not as evidence for product readiness. Real execution was not claimed because the frozen corpus contains no exact environment/command/lockfile/container manifest.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    episode_artifact = _read(V05_EVIDENCE)
    episodes = cast(list[dict[str, Any]], episode_artifact["episodes"])
    views = cast(list[dict[str, Any]], episode_artifact["candidate_views"])
    experiment_metrics = _read(EVIDENCE / "experiment-metrics.json")
    runs = cast(list[dict[str, Any]], experiment_metrics["runs"])
    v05_result = _read(ROOT / "artifacts" / "v05-result.json")
    frozen_metrics = cast(dict[str, Any], v05_result["lanes"]["B_deterministic_heuristic"]["metrics"])
    safety = safety_results(episodes, runs)
    action_space = action_space_audit(views)
    metadata = metadata_channel_audit(episodes, views, ROOT)
    grouped = grouped_holdout_audit(episodes, runs, group_field="incident")
    cross_family = grouped_holdout_audit(episodes, runs, group_field="family")
    component_holdout = grouped_holdout_audit(episodes, runs, group_field="component")
    time_period_holdout = grouped_holdout_audit(episodes, runs, group_field="time_period")
    decoys = decoy_audit(episodes, views, ROOT)
    anti_oracle = anti_oracle_baselines(episodes, views, ROOT)
    counterfactual = counterfactual_audit(episodes, views, ROOT)
    real_execution = real_execution_audit(ROOT, episodes)
    concordance = replay_concordance_audit(real_execution)
    freeze = investigator_freeze_audit(ROOT, v05_result["hashes"]["implementation"], "60ccc18")
    gates = v06_gates(action_space, metadata, decoys, anti_oracle, counterfactual, real_execution, concordance, frozen_metrics, safety, freeze)
    findings = [
        f"Metadata-only owner prediction is {metadata['metadata_gate_value']} against chance {metadata['chance_baseline']}.",
        f"The full result channel exposes supported components on {metadata['direct_result_component_exposure_count']} of {metadata['episodes']} probes.",
        f"Decoy false-useful rate on attribution cases is {decoys['attribution_decoy_false_useful_rate']['value']} (overall {decoys['decoy_false_useful_rate']['value']}).",
        f"Random attribution resolution is {anti_oracle['random_valid_experiment_selection']['attribution_resolution']['value']}; naive is {anti_oracle['naive_first_component_heuristic']['attribution_resolution']['value']}.",
        f"Oracle-availability-only attribution resolution is {anti_oracle['oracle_availability_only_planner']['attribution_resolution']['value']} using response status only.",
        "No real execution subset or replay/execution concordance is available from the frozen corpus.",
    ]
    statuses = {
        "V06_BENCHMARK_INTEGRITY": "VALIDATED" if gates["integrity_validated"] else "FAILED_VALIDATION",
        "V05_INVESTIGATOR": "FROZEN_UNDER_AUDIT",
        "PRODUCT_IMPLEMENTATION": "BLOCKED" if not gates["integrity_validated"] else "NOT_STARTED",
    }
    hashes = {
        "immutable_v04_corpus": v05_result["hashes"]["immutable_v04_corpus"],
        "frozen_v05_implementation": v05_result["hashes"]["implementation"],
        "v06_audit_implementation": _implementation_digest(),
    }
    result = {
        "protocol_version": "0.6",
        "project": "ecosystem-radar-bench",
        "decision": gates["decision"],
        "statuses": statuses,
        "scope": {"investigator_tuned": False, "corpus_expanded": False, "episodes": len(episodes), "real_execution": real_execution["status"], "network_mutation": "none"},
        "hashes": hashes,
        "platform": {"python": platform.python_version(), "platform": platform.platform()},
        "gates": gates,
        "findings": findings,
        "artifact_paths": [
            "artifacts/v06-final-report.md",
            "artifacts/v06-result.json",
            *[f"artifacts/release-evidence/{name}" for name in REQUIRED_V06_ARTIFACTS],
        ],
    }
    _write(EVIDENCE / "oracle-channel-audit-v06.json", {"schema_version": "0.1", "action_space": action_space, "metadata_channel": metadata})
    _write(EVIDENCE / "grouped-holdout-v06.json", grouped)
    _write(EVIDENCE / "cross-family-holdout-v06.json", cross_family)
    _write(EVIDENCE / "component-holdout-v06.json", component_holdout)
    _write(EVIDENCE / "time-period-holdout-v06.json", time_period_holdout)
    _write(EVIDENCE / "decoy-experiments-v06.json", decoys)
    _write(EVIDENCE / "counterfactual-perturbations-v06.json", counterfactual)
    _write(EVIDENCE / "anti-oracle-baselines-v06.json", anti_oracle)
    _write(EVIDENCE / "real-execution-v06.json", real_execution)
    _write(EVIDENCE / "replay-concordance-v06.json", concordance)
    _write(EVIDENCE / "investigator-freeze-v06.json", freeze)
    _write(EVIDENCE / "v06-gates.json", gates)
    _write(ROOT / "artifacts" / "v06-result.json", result)
    (ROOT / "artifacts" / "v06-final-report.md").write_text(_report(result, gates, findings), encoding="utf-8", newline="\n")
    print(json.dumps({"valid": True, "decision": result["decision"], "statuses": statuses, "gates": gates["checks"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
