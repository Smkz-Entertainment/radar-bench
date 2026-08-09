"""Run the v0.7 executable investigation benchmark or fail closed."""

from __future__ import annotations

import json
import platform
import random
from pathlib import Path
from typing import Any, cast

from radar_bench.evaluation.stages import digest_tree
from radar_bench.execution.v07 import (
    FROZEN_V05_COMMIT,
    REQUIRED_V07_ARTIFACTS,
    HermeticExecutor,
    adapt_frozen_request,
    evaluate_pilot,
    freeze_audit,
    preparation_audit,
    validate_manifest,
    v07_gates,
)
from radar_bench.investigation.v01 import HeuristicInvestigator

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts" / "release-evidence"
MANIFEST = ROOT / "corpus" / "v0.7" / "executable-subset.json"
EVALUATOR_GOLD = ROOT / "corpus" / "v0.7" / "evaluator-gold.json"


def _read(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _implementation_digest() -> str:
    return digest_tree(ROOT, ("src/radar_bench/execution/*.py", "scripts/run_v07_executable.py"))


def _no_experiment_run(case_id: str) -> dict[str, Any]:
    return {
        "episode_id": case_id,
        "terminal": {"state": "BOUNDED_INCONCLUSIVE", "root_cause_component": None, "action_owner_repository": None},
        "attempts": [],
    }


def _naive_run(view: dict[str, Any], executor: HermeticExecutor) -> dict[str, Any]:
    episode_id = view["episode_id"]
    baseline = executor.execute({"schema_version": "0.7", "request_id": f"V07-NAIVE-B-{episode_id}", "episode_id": episode_id, "capability": "rerun", "parameters": {}})
    probe = executor.execute({"schema_version": "0.7", "request_id": f"V07-NAIVE-P-{episode_id}", "episode_id": episode_id, "capability": "change_dependency_version", "parameters": {"target_component": "upstream_component"}})
    result = probe.get("result", {})
    if result.get("outcome") == "CANDIDATE_SPECIFIC":
        terminal = {"state": "CAUSALLY_ATTRIBUTED", "root_cause_component": "upstream_component", "action_owner_repository": "upstream_component"}
    else:
        terminal = {"state": "BOUNDED_INCONCLUSIVE", "root_cause_component": None, "action_owner_repository": None}
    return {"episode_id": episode_id, "terminal": terminal, "attempts": [{"response": baseline, "useful": bool(baseline.get("result", {}).get("useful"))}, {"response": probe, "useful": bool(result.get("useful"))}]}


def _random_run(view: dict[str, Any], executor: HermeticExecutor, rng: random.Random) -> dict[str, Any]:
    capability = rng.choice(["change_dependency_version", "freeze_dependency", "bisect_component", "toggle_environment_variable", "run_minimal_test", "inspect_dependency_graph"])
    response = executor.execute({"schema_version": "0.7", "request_id": f"V07-RANDOM-{view['episode_id']}", "episode_id": view["episode_id"], "capability": capability, "parameters": {}})
    result = response.get("result", {})
    terminal = {"state": "CAUSALLY_ATTRIBUTED", "root_cause_component": "upstream_component", "action_owner_repository": "upstream_component"} if result.get("outcome") == "CANDIDATE_SPECIFIC" else {"state": "BOUNDED_INCONCLUSIVE", "root_cause_component": None, "action_owner_repository": None}
    return {"episode_id": view["episode_id"], "selected_capability": capability, "terminal": terminal, "attempts": [{"response": response, "useful": bool(result.get("useful"))}]}


def _execute_cases(manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    executor = HermeticExecutor(manifest, root=ROOT)
    radar_runs: list[dict[str, Any]] = []
    naive_runs: list[dict[str, Any]] = []
    no_experiment_runs: list[dict[str, Any]] = []
    random_runs: list[dict[str, Any]] = []
    rng = random.Random(20260809)  # nosec B311 - deterministic non-security baseline
    for case in cast(list[dict[str, Any]], manifest["cases"]):
        view = _read(ROOT / case["candidate_view"])
        radar_runs.append(HeuristicInvestigator(root=ROOT).run(view, lambda request: executor.execute(adapt_frozen_request(request))))
        naive_runs.append(_naive_run(view, executor))
        no_experiment_runs.append(_no_experiment_run(case["case_id"]))
        random_runs.append(_random_run(view, executor, rng))
    return radar_runs, naive_runs, no_experiment_runs, random_runs


def _report(result: dict[str, Any], preparation: dict[str, Any], gates: dict[str, Any]) -> str:
    lines = [
        "# Radar Bench v0.7 Executable Investigation Benchmark",
        "",
        "v0.7 keeps commit 60ccc18 frozen and replaces historical replay certification with sealed, network-denied execution. It does not implement a product.",
        "",
        "## Decision",
        "",
        f"- Product validation: `{result['statuses']['PRODUCT_VALIDATION']}`.",
        f"- Agentic causal investigation: `{result['statuses']['AGENTIC_CAUSAL_INVESTIGATION']}`.",
        f"- v0.5 investigator: `{result['statuses']['V05_INVESTIGATOR']}`.",
        f"- Decision: `{result['decision']}`.",
        "",
        "## Preparation boundary",
        "",
        f"- Status: `{preparation['status']}`.",
        f"- Cases: `{preparation.get('case_count', 0)}`.",
        f"- Reason: {str(preparation.get('reason', 'none')).rstrip('.')}.",
        "",
        "## Gates",
        "",
    ]
    if gates["checks"]:
        lines.extend(f"- `{name}`: `{item['status']}` (value `{item['value']}`, threshold `{item['threshold']}`)." for name, item in gates["checks"].items())
    else:
        lines.append("- No executable metrics were scored because the sealed corpus is unavailable.")
    lines.extend([
        "",
        "Historical replay remains available for development and qualitative research, but it is not used to certify v0.7. No synthetic execution, gold-mounted runtime, or availability-derived result was substituted.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    preparation = preparation_audit(ROOT, MANIFEST)
    manifest = _read(MANIFEST) if MANIFEST.exists() else {"cases": []}
    manifest_errors = validate_manifest(manifest, root=ROOT) if MANIFEST.exists() else ["manifest is absent"]
    preparation_with_validation = {**preparation, "manifest_validation_errors": manifest_errors}
    freeze_expected = _read(ROOT / "artifacts" / "v05-result.json")["hashes"]["implementation"]
    freeze = freeze_audit(ROOT, freeze_expected, FROZEN_V05_COMMIT)
    runs: list[dict[str, Any]] = []
    naive_runs: list[dict[str, Any]] = []
    no_experiment_runs: list[dict[str, Any]] = []
    random_runs: list[dict[str, Any]] = []
    metrics: dict[str, Any] = evaluate_pilot([], [], [], [])
    if preparation["status"] == "READY":
        if not EVALUATOR_GOLD.exists():
            preparation_with_validation["status"] = "BLOCKED_BY_EXECUTABILITY"
            preparation_with_validation["reason"] = "Evaluator-only gold labels are not sealed separately from the runtime manifest."
        else:
            runs, naive_runs, no_experiment_runs, random_runs = _execute_cases(manifest)
            labels = _read(EVALUATOR_GOLD)
            cases = cast(list[dict[str, Any]], manifest["cases"])
            for case in cases:
                case["gold"] = labels[case["case_id"]]
            metrics = evaluate_pilot(cases, runs, naive_runs, no_experiment_runs, random_runs)
    gates = v07_gates(metrics, preparation_with_validation, freeze)
    statuses = {
        "PRODUCT_VALIDATION": gates["product_validation"],
        "AGENTIC_CAUSAL_INVESTIGATION": gates["agentic_causal_investigation"],
        "V05_INVESTIGATOR": "FROZEN_UNDER_AUDIT",
        "SAFE_ABSTENTION_MACHINERY": "PROMISING",
        "REPLAY_ORACLE_CERTIFICATION": "REJECTED",
    }
    result = {
        "protocol_version": "0.7",
        "project": "ecosystem-radar-bench",
        "decision": gates["decision"],
        "statuses": statuses,
        "scope": {
            "candidate_commit": FROZEN_V05_COMMIT,
            "investigator_tuned": False,
            "historical_replay_certification": "forbidden",
            "network_policy": "denied",
            "gold_mounted": False,
            "case_count": preparation_with_validation.get("case_count", 0),
            "host_platform": platform.platform(),
        },
        "hashes": {
            "frozen_v05_implementation": freeze_expected,
            "v07_implementation": _implementation_digest(),
        },
        "preparation": preparation_with_validation,
        "freeze": freeze,
        "metrics": metrics,
        "gates": gates,
        "artifact_paths": [
            "artifacts/v07-final-report.md",
            "artifacts/v07-result.json",
            *[f"artifacts/release-evidence/{name}" for name in REQUIRED_V07_ARTIFACTS],
        ],
    }
    _write(EVIDENCE / "v07-manifest-validation.json", preparation_with_validation)
    _write(EVIDENCE / "v07-preparation-audit.json", preparation_with_validation)
    _write(EVIDENCE / "v07-freeze-audit.json", freeze)
    _write(EVIDENCE / "v07-execution-runs.json", {"runs": runs, "naive_runs": naive_runs, "random_runs": random_runs, "no_experiment_runs": no_experiment_runs, "metrics": metrics})
    _write(EVIDENCE / "v07-gates.json", gates)
    _write(ROOT / "artifacts" / "v07-result.json", result)
    (ROOT / "artifacts" / "v07-final-report.md").write_text(_report(result, preparation_with_validation, gates), encoding="utf-8", newline="\n")
    print(json.dumps({"valid": True, "decision": result["decision"], "statuses": statuses, "case_count": result["scope"]["case_count"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
