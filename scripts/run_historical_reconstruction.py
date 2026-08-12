"""Run the five sealed decisive-v1.2 historical recipes and record receipts."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from radar_bench.v12_executor import V12ExperimentExecutor


def _contract_pass(runtime: dict[str, Any], result: dict[str, Any]) -> bool:
    if result.get("status") not in {"COMPLETED", "OBSERVED_FAILURE"}:
        return False
    observation = result.get("observation")
    receipt = result.get("evaluator_receipt")
    if not isinstance(observation, dict) or not isinstance(receipt, dict):
        return False
    if not all(receipt.get(key) is True for key in ("fresh", "available", "cleanup_verified")):
        return False
    control = observation.get("control")
    candidate = observation.get("candidate")
    expected = runtime.get("expected")
    if not isinstance(control, dict) or not isinstance(candidate, dict) or not isinstance(expected, dict):
        return False
    return control.get("returncode") == expected.get("control_exit") and candidate.get("returncode") == expected.get("candidate_exit")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    artifact_root = root / "artifacts" / "external" / "decisive-v1.2"
    output = root / "artifacts" / "v1.1.0" / "runtime-reconstruction.json"
    executor = V12ExperimentExecutor(
        root,
        episode_to_case={f"historical-{index:02d}": f"RADAR-V07-A{index:02d}" for index in range(1, 6)},
        artifact_root=artifact_root,
    )
    case_ids = [f"RADAR-V07-A{index:02d}" for index in range(1, 6)]
    records: list[dict[str, Any]] = []
    for index, case_id in enumerate(case_ids, start=1):
        runtime = executor.recipes.get(case_id)
        if runtime is None:
            records.append({"case_id": case_id, "status": "NOT_RUN", "contract_pass": False})
            continue
        started = time.perf_counter()
        result = dict(executor(f"historical-{index:02d}", {"capability": "rerun", "parameters": {}}))
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        record = {
            "case_id": case_id,
            "request": {"capability": "rerun", "parameters": {}},
            "elapsed_ms": elapsed_ms,
            "contract_pass": _contract_pass(dict(runtime), result),
            "result": result,
        }
        records.append(record)
        print(json.dumps({"case_id": case_id, "contract_pass": record["contract_pass"], "status": result.get("status")}), flush=True)
    passed = sum(1 for record in records if record.get("contract_pass") is True)
    document = {
        "schema_version": "1",
        "suite_id": "decisive-v1.2",
        "artifact_status": {
            "status": executor.artifact_status.get("status"),
            "network_used": executor.artifact_status.get("network_used"),
            "catalog_digest": executor.artifact_status.get("catalog_digest"),
        },
        "execution_policy": {
            "evaluator_gold_loaded": False,
            "candidate_bundle_loaded": False,
            "request": {"capability": "rerun", "parameters": {}},
        },
        "historical_case_count": len(case_ids),
        "records": records,
        "summary": {
            "executed": sum(1 for record in records if record.get("result", {}).get("evaluator_receipt")),
            "contract_pass": passed,
            "status": "PASS" if passed == len(case_ids) else "BLOCKED",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if passed == len(case_ids) else 2


if __name__ == "__main__":
    raise SystemExit(main())
