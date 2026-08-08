"""Detect post-cutoff evidence and gold identifiers in inference packets."""

from __future__ import annotations

import json
from typing import Any

from radar_bench.snapshots.cutoff import parse_cutoff, visible_before_cutoff


def scan_leakage(case: dict[str, Any], input_payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    cutoff = parse_cutoff(case["provenance"]["source_snapshot_cutoff"])
    input_text = json.dumps(input_payload, sort_keys=True)
    visible_ids = set(input_payload.get("evidence_ids", []))
    visible_uris = {
        item.get("uri")
        for item in case.get("evidence", [])
        if item.get("evidence_id") in visible_ids
    }
    for evidence in case.get("evidence", []):
        allowed, reason = visible_before_cutoff(evidence, cutoff)
        if not allowed:
            if evidence["evidence_id"] in visible_ids:
                errors.append(
                    f"post-cutoff evidence leaked: {evidence['evidence_id']} ({reason})"
                )
            if evidence["uri"] in input_text and evidence["uri"] not in visible_uris:
                errors.append(f"gold URI leaked: {evidence['uri']}")
    gold = case.get("resolution") or {}
    for key in ("issue", "pull_request", "revision", "version"):
        value = gold.get(key) if isinstance(gold, dict) else None
        if value and str(value) in input_text:
            errors.append(f"resolution {key} leaked")
    for item in case.get("evidence", []):
        if (
            item.get("available_before_cutoff") is False
            and item["evidence_id"] in input_text
        ):
            errors.append(f"gold evidence identifier leaked: {item['evidence_id']}")
    return errors
