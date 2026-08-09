"""Run the bounded, replay-first Radar Bench v0.5 investigation pilot."""

from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path
from typing import Any, cast

from radar_bench.evaluation.stages import digest_tree
from radar_bench.evaluation.v05 import (
    ablation_summary,
    lane_metrics,
    resolution_at_k,
    safety_results,
    v05_gates,
)
from radar_bench.investigation.v01 import (
    HeuristicInvestigator,
    ReplayOracle,
    build_candidate_view,
    build_episode,
    validate_episode,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "corpus" / "v0.4" / "pilot"
EVIDENCE = ROOT / "artifacts" / "release-evidence"


def _read(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _hashes() -> dict[str, str]:
    return {
        "immutable_v04_corpus": digest_tree(ROOT, ("corpus/v0.4/pilot/**/*.json",)),
        "implementation": digest_tree(
            ROOT,
            (
                "src/radar_bench/investigation/*.py",
                "src/radar_bench/evaluation/v05.py",
                "schema/investigation-*.json",
                "scripts/run_v05_investigation.py",
            ),
        ),
    }


def _static_baseline(v04: dict[str, Any]) -> dict[str, Any]:
    checks = v04["early_gates"]["checks"]
    return {
        "lane": "A_static_v04",
        "status": "FROZEN",
        "source_artifact": "artifacts/v04-result.json",
        "metrics": {
            "candidate_induced_precision": checks["candidate_induced_precision"]["value"],
            "action_owner_precision": checks["action_owner_precision"]["value"],
            "safety_abstention_recall": checks["abstention_recall"]["value"],
            "false_high_confidence_owner_accusations": checks["false_high_confidence_upstream"]["value"],
        },
        "v04_decision_unchanged": v04["decision"],
    }


def _attributability(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "episode_id": episode["episode_id"],
            "case_id": episode["case_id"],
            "corpus_kind": episode["corpus_kind"],
            "difficulty": episode["difficulty"],
            "attributability_class": episode["gold"]["attributability_class"],
            "justification": episode["gold"]["justification"],
            "source_evidence_ids": episode["gold"]["source_evidence_ids"],
            "provenance": episode["provenance"],
        }
        for episode in episodes
    ]


def _temporal_blindness(episodes: list[dict[str, Any]], views: list[dict[str, Any]]) -> dict[str, Any]:
    forbidden = {"gold", "hidden_gold_packet", "historical_evidence", "label", "action_owner_repository", "root_cause_component", "attributability_class"}
    leaked: list[str] = []
    for episode, view in zip(episodes, views):
        view_text = json.dumps(view, sort_keys=True)
        if any(f'"{key}"' in view_text for key in forbidden):
            leaked.append(episode["episode_id"])
        if set(episode["hidden_gold_packet"]["evidence_ids"]) & set(view["candidate_snapshot"]["visible_evidence_ids"]):
            leaked.append(episode["episode_id"] + ":evidence-overlap")
    return {
        "candidate_views": len(views),
        "hidden_fields_checked": sorted(forbidden),
        "leakage_count": len(leaked),
        "leaked_episode_ids": leaked,
        "valid": not leaked,
        "policy": "Candidate receives cutoff snapshot, observations, hypotheses, action space, and replay results only.",
    }


def _report(
    hashes: dict[str, str], metrics: dict[str, Any], gates: dict[str, Any],
    safety: dict[str, Any], runs: list[dict[str, Any]], statuses: dict[str, str],
) -> str:
    lines = [
        "# Radar Bench v0.5 Interactive Regression Investigation",
        "",
        "This is a bounded replay-first experiment on the committed v0.4 corpus. The v0.4 corpus, labels, and authoritative result are unchanged.",
        "",
        "## Status",
        "",
        f"- `STATIC_OWNER_ATTRIBUTION`: `{statuses['STATIC_OWNER_ATTRIBUTION']}`; frozen v0.4 decision remains `PIVOT_REQUIRED`.",
        f"- `AGENTIC_CAUSAL_INVESTIGATION`: `{statuses['AGENTIC_CAUSAL_INVESTIGATION']}`.",
        f"- Episodes: `{len(runs)}`; substantive experiments: `{sum(run['substantive_experiments'] for run in runs)}`.",
        f"- Immutable corpus digest: `{hashes['immutable_v04_corpus']}`.",
        f"- Implementation digest: `{hashes['implementation']}`.",
        "",
        "## Lane B results",
        "",
        f"- Candidate-induced precision: `{metrics['candidate_induced']['precision']['value']}`.",
        f"- Action-owner precision on attributable claims: `{metrics['action_owner']['precision']['value']}`.",
        f"- Correct resolution or abstention: `{metrics['correct_resolution_or_abstention']['value']}`.",
        f"- Useful experiment rate: `{metrics['experiment_quality']['useful_rate']['value']}`.",
        f"- Median experiments per resolution: `{metrics['efficiency']['experiments_per_resolution']}`.",
        f"- Safety abstention recall: `{safety['abstention_recall']['value']}`.",
        "",
        "## Gates",
        "",
    ]
    lines.extend(f"- `{name}`: `{item['status']}` (value `{item['value']}`, threshold `{item['threshold']}`)." for name, item in gates["checks"].items())
    lines.extend([
        "",
        "The experiment interface is replay-only for this pilot because the corpus is historical and no safe, secret-free container reproduction was available. No candidate lane receives future comments, gold owners, or resolution text. The next action for an unresolved case is another permitted experiment or abstention; it is never a highest-probability owner guess.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    records = [_read(path) for path in sorted((PILOT / "records").glob("*.json"))]
    records = [item for item in records if item["admission_state"] == "admitted"]
    episodes = [build_episode(record, root=ROOT) for record in records]
    views = [build_candidate_view(episode) for episode in episodes]
    episode_errors = [
        f"{episode['episode_id']}: {error}"
        for episode in episodes
        for error in validate_episode(episode, root=ROOT)
    ]
    if episode_errors:
        raise ValueError("episode validation failed: " + "; ".join(episode_errors))
    blindness = _temporal_blindness(episodes, views)
    if not blindness["valid"]:
        raise ValueError("temporal blindness failed")
    oracle = ReplayOracle(episodes, root=ROOT)
    investigator = HeuristicInvestigator(root=ROOT)
    runs = [investigator.run(view, oracle.execute) for view in views]
    metrics = lane_metrics(episodes, runs)
    safety = safety_results(episodes, runs)
    gates = v05_gates(metrics, safety)
    v04 = _read(ROOT / "artifacts" / "v04-result.json")
    hashes = _hashes()
    statuses = {
        "STATIC_OWNER_ATTRIBUTION": "FAILED_VALIDATION",
        "AGENTIC_CAUSAL_INVESTIGATION": "FAILED_VALIDATION" if gates["kill_criteria_triggered"] else "ACTIVE_VALIDATED" if gates["continue_pilot"] else "ACTIVE_UNVALIDATED",
    }
    invalid_probe = oracle.execute({"schema_version": "0.1", "request_id": "REQ-INVALID", "episode_id": episodes[0]["episode_id"], "experiment_id": "EXP-INVALID", "type": "version_swap", "hypothesis": "", "limits": {"network_policy": "denied", "timeout_seconds": 30, "memory_mb": 256, "output_mb": 10}})
    lane_b = {"lane": "B_deterministic_heuristic", "status": "RUN", "metrics": metrics}
    lanes = {"A_static_v04": _static_baseline(v04), "B_deterministic_heuristic": lane_b, "C_local_open_model": {"status": "BLOCKED_EXTERNAL", "reason": "No suitable no-cost local model is installed."}, "D_codex_openai": {"status": "BLOCKED_EXTERNAL", "reason": "No credentials or credits were available; no purchase attempted."}}
    _write(EVIDENCE / "investigation-episodes.json", {"schema_version": "0.1", "episodes": episodes, "candidate_views": views})
    _write(EVIDENCE / "attributability.json", {"schema_version": "0.1", "records": _attributability(episodes)})
    _write(EVIDENCE / "experiment-metrics.json", {"schema_version": "0.1", "lane": "B_deterministic_heuristic", "metrics": metrics, "runs": runs, "interface_contract": {"invalid_probe": invalid_probe}})
    _write(EVIDENCE / "resolution-at-k.json", resolution_at_k(episodes, runs))
    _write(EVIDENCE / "safety-results.json", safety)
    # v0.3 already owns ablation-results.json; retain that frozen artifact and
    # version the v0.5 comparison explicitly.
    _write(EVIDENCE / "ablation-results-v05.json", ablation_summary(lanes))
    _write(EVIDENCE / "temporal-blindness-v05.json", blindness)
    _write(EVIDENCE / "v05-gates.json", gates)
    result = {
        "protocol_version": "0.5",
        "project": "ecosystem-radar-bench",
        "decision": "STOP_AND_ABSTAIN" if gates["kill_criteria_triggered"] else "CONTINUE_BOUNDED_PILOT" if gates["continue_pilot"] else "ACTIVE_UNVALIDATED",
        "statuses": statuses,
        "scope": {"admitted_attribution": 20, "admitted_safety": 40, "corpus_expansion": False, "real_container_adapter": "not_run", "replay_adapter": "historical_replay"},
        "hashes": hashes,
        "implementation_commit_at_generation": _commit(),
        "platform": {"python": platform.python_version(), "platform": platform.platform()},
        "gates": gates,
        "safety": safety,
        "lanes": {name: {key: value for key, value in lane.items() if key != "runs"} for name, lane in lanes.items()},
        "artifact_paths": [
            "artifacts/v05-final-report.md", "artifacts/release-evidence/v05-gates.json", "artifacts/release-evidence/investigation-episodes.json", "artifacts/release-evidence/attributability.json", "artifacts/release-evidence/experiment-metrics.json", "artifacts/release-evidence/resolution-at-k.json", "artifacts/release-evidence/safety-results.json", "artifacts/release-evidence/ablation-results-v05.json", "artifacts/release-evidence/temporal-blindness-v05.json",
        ],
    }
    _write(ROOT / "artifacts" / "v05-result.json", result)
    (ROOT / "artifacts" / "v05-final-report.md").write_text(_report(hashes, metrics, gates, safety, runs, statuses), encoding="utf-8", newline="\n")
    print(json.dumps({"valid": True, "decision": result["decision"], "statuses": statuses, "gates": gates["checks"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
