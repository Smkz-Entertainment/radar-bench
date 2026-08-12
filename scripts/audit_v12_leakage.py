"""Run a candidate-visible content leakage attack for decisive-v1.2."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

HISTORICAL_PREFIX = "RADAR-V07-A"
SAFETY_PREFIX = "RADAR-V07-T"
ADVANTAGE_THRESHOLD = 0.2


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _tokens(value: Any) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9_.-]{3,}", json.dumps(value, sort_keys=True).lower()))


def audit(root: Path) -> dict[str, Any]:
    candidate_path = root / "candidate/decisive-v1.2/candidate-bundle.json"
    evaluator_path = root / "evaluator/decisive-v1.2/evaluator-bundle.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    evaluator = json.loads(evaluator_path.read_text(encoding="utf-8"))
    mapping = evaluator["record_case_mapping"]
    rows = [
        (str(item["record_id"]), str(mapping[item["record_id"]]), _tokens(item["evidence"]))
        for item in candidate["cases"]
    ]

    def similarity(left: set[str], right: set[str]) -> float:
        return len(left & right) / max(1, len(left | right))

    outcomes: list[dict[str, Any]] = []
    for record_id, case_id, features in rows:
        historical_scores: list[float] = []
        safety_scores: list[float] = []
        for other_id, other_case_id, other_features in rows:
            if other_id == record_id:
                continue
            score = similarity(features, other_features)
            (historical_scores if other_case_id.startswith(HISTORICAL_PREFIX) else safety_scores).append(score)
        historical_mean = sum(historical_scores) / max(1, len(historical_scores))
        safety_mean = sum(safety_scores) / max(1, len(safety_scores))
        predicted_historical = historical_mean > safety_mean
        actual_historical = case_id.startswith(HISTORICAL_PREFIX)
        outcomes.append(
            {
                "record_id": record_id,
                "case_id": case_id,
                "historical_similarity": round(historical_mean, 6),
                "safety_similarity": round(safety_mean, 6),
                "advantage": round(abs(historical_mean - safety_mean), 6),
                "predicted_historical": predicted_historical,
                "actual_historical": actual_historical,
                "correct": predicted_historical == actual_historical,
            }
        )

    historical = [item for item in outcomes if item["actual_historical"]]
    safety = [item for item in outcomes if not item["actual_historical"]]
    historical_accuracy = sum(int(item["correct"]) for item in historical) / max(1, len(historical))
    safety_accuracy = sum(int(item["correct"]) for item in safety) / max(1, len(safety))
    balanced_accuracy = (historical_accuracy + safety_accuracy) / 2
    max_advantage = max((float(item["advantage"]) for item in outcomes), default=0.0)
    status = "PASS" if max_advantage <= ADVANTAGE_THRESHOLD and abs(balanced_accuracy - 0.5) <= ADVANTAGE_THRESHOLD else "BLOCKED"
    return {
        "status": status,
        "method": "Leave-one-out nearest-neighbor group-mean similarity over candidate-visible content tokens; evaluator mapping is used only to score the attack.",
        "case_count": len(outcomes),
        "historical_count": len(historical),
        "safety_count": len(safety),
        "historical_accuracy": historical_accuracy,
        "safety_accuracy": safety_accuracy,
        "balanced_accuracy": balanced_accuracy,
        "balanced_accuracy_excess_over_chance": abs(balanced_accuracy - 0.5),
        "max_group_mean_advantage": max_advantage,
        "preregistered_advantage_threshold": ADVANTAGE_THRESHOLD,
        "candidate_bundle_digest": _digest(candidate),
        "evaluator_mapping_digest": _digest(mapping),
        "outcomes": outcomes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.root.resolve())
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8", newline="\n")
    else:
        print(encoded, end="")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
