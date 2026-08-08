"""Build separate machine-readable input and gold snapshot products."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from radar_bench.models.case import validate_case
from radar_bench.snapshots.cutoff import parse_cutoff, visible_before_cutoff
from radar_bench.snapshots.leakage import scan_leakage


def build_snapshot(
    case: dict[str, Any], target: Path, *, root: Path | None = None
) -> dict[str, Any]:
    errors = validate_case(case, root=root)
    if errors:
        raise ValueError("case is invalid: " + "; ".join(errors))
    cutoff = parse_cutoff(case["provenance"]["source_snapshot_cutoff"])
    visible: list[dict[str, Any]] = []
    hidden: list[dict[str, Any]] = []
    for item in case["evidence"]:
        (visible if visible_before_cutoff(item, cutoff)[0] else hidden).append(
            copy.deepcopy(item)
        )
    visible_ids = {item["evidence_id"] for item in visible}
    input_payload = {
        "schema_version": "0.1",
        "case_id": case["case_id"],
        "cutoff": case["provenance"]["source_snapshot_cutoff"],
        "upstream_change": case["upstream_change"],
        "downstream_subject": case["downstream_subject"],
        "environments": case["environments"],
        "outcomes": _filter_outcomes(case["outcomes"], visible_ids),
        "failure": case.get("failure"),
        "hypotheses": _filter_hypotheses(case.get("hypotheses", []), visible_ids),
        "experiments": _filter_experiments(case.get("experiments", []), visible_ids),
        "evidence": visible,
        "evidence_ids": sorted(visible_ids),
        "attribution": {
            "candidate_induced": None,
            "responsible_layer": "unknown",
            "owner_repository": None,
            "owner_project": None,
            "intentionality": "unknown",
            "first_bad": None,
            "evidence_tier": "UNLABELED",
            "confidence": "inconclusive",
            "rationale": "Gold resolution evidence is hidden from inference.",
        },
    }
    leakage = scan_leakage(case, input_payload)
    if leakage:
        raise ValueError("snapshot leakage detected: " + "; ".join(leakage))
    target.mkdir(parents=True, exist_ok=True)
    (target / "input").mkdir(exist_ok=True)
    (target / "gold").mkdir(exist_ok=True)
    _write(target / "input" / "snapshot.json", input_payload)
    _write(
        target / "input" / "evidence.json",
        {
            "evidence": visible,
            "decisions": {
                item["evidence_id"]: visible_before_cutoff(item, cutoff)[1]
                for item in case["evidence"]
            },
        },
    )
    _write(
        target / "gold" / "label.json",
        {
            "case_id": case["case_id"],
            "attribution": case["attribution"],
            "resolution": case.get("resolution"),
            "evidence_ids": [item["evidence_id"] for item in hidden],
        },
    )
    _write(target / "gold" / "evidence.json", {"evidence": hidden})
    _write(
        target / "metadata.json",
        {
            "case_id": case["case_id"],
            "t0": case["lifecycle"]["observed_at"],
            "tcut": case["provenance"]["source_snapshot_cutoff"],
            "tgold": case["lifecycle"].get("updated_at"),
            "visible_count": len(visible),
            "gold_count": len(hidden),
        },
    )
    (target / "README.md").write_text(
        "# "
        + case["case_id"]
        + "\n\nInput evidence is the evaluated snapshot. Gold evidence is curator-only and must not be loaded by inference providers.\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "case_id": case["case_id"],
        "visible_count": len(visible),
        "gold_count": len(hidden),
        "leakage": [],
    }


def _filter_outcomes(outcomes: dict[str, Any], ids: set[str]) -> dict[str, Any]:
    result = copy.deepcopy(outcomes)
    for item in result.values():
        item["evidence_ids"] = [
            value for value in item.get("evidence_ids", []) if value in ids
        ]
    return result


def _filter_hypotheses(
    items: list[dict[str, Any]], ids: set[str]
) -> list[dict[str, Any]]:
    result = []
    for item in items:
        current = copy.deepcopy(item)
        current["experiment_ids"] = []
        result.append(current)
    return result


def _filter_experiments(
    items: list[dict[str, Any]], ids: set[str]
) -> list[dict[str, Any]]:
    result = []
    for item in items:
        current = copy.deepcopy(item)
        current["evidence_ids"] = [
            value for value in current.get("evidence_ids", []) if value in ids
        ]
        if current["evidence_ids"]:
            result.append(current)
    return result


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
