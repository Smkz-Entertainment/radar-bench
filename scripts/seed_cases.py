"""Materialize the honest, status-marked seed records from corpus/manifest.csv."""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def owner_uri(value: str) -> str | None:
    match = re.search(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", value)
    return (
        f"https://github.com/{match.group(1)}"
        if match and not value.startswith("mixed:")
        else None
    )


def make_case(row: dict[str, str]) -> dict:
    date = row["signal_date"] + "T00:00:00Z"
    source_urls = row["source_urls"].split(";")
    source_id = "E-" + row["case_id"].replace("-", "_")
    layer = row["gold_responsible_layer"]
    if layer == "unknown/multiple_layers":
        layer = "multiple_layers"
    abstain = row["should_abstain"].lower() == "true"
    candidate_induced = (
        None
        if abstain
        else layer
        not in {
            "external_service_or_data",
            "ci_or_infrastructure",
            "flaky_or_nondeterministic",
            "unknown",
        }
    )
    status = "inconclusive" if abstain else "resolved"
    event = row["event_type"].lower()
    phase = (
        "external_service"
        if "external" in event or "404" in row["observed_failure"]
        else "artifact_availability"
        if "artifact" in event or "wheel" in event
        else "runtime"
    )
    evidence = [
        {
            "evidence_id": source_id,
            "kind": "issue",
            "uri": source_urls[0],
            "digest": None,
            "collected_at": date,
            "available_before_cutoff": True,
            "notes": "Seed-manifest source reference; public content must be independently collected before a headline result.",
        }
    ]
    experiments = []
    hypotheses = []
    if row["label_tier"] == "A":
        experiments = [
            {
                "experiment_id": "X-" + row["case_id"].replace("-", "_"),
                "question": "Does a controlled intervention distinguish the candidate from the control?",
                "intervention": "Run a bounded control/candidate comparison with the environment held stable.",
                "status": "supported",
                "result_summary": "Curator manifest records a causal or resolution-grade signal; details remain linked public evidence.",
                "evidence_ids": [source_id],
                "proposed_by": "human",
            }
        ]
        hypotheses = [
            {
                "hypothesis_id": "H-" + row["case_id"].replace("-", "_"),
                "description": row["observed_failure"],
                "proposed_by": "human",
                "status": "supported",
                "experiment_ids": [experiments[0]["experiment_id"]],
            }
        ]
    owner = owner_uri(row["gold_owner"])
    return {
        "schema_version": "0.1",
        "case_id": row["case_id"],
        "title": row["event_type"],
        "summary": row["observed_failure"],
        "lifecycle": {
            "state": status,
            "observed_at": date,
            "updated_at": date,
            "closed_at": None,
        },
        "upstream_change": {
            "kind": "library",
            "ecosystem": "public Python ecosystem",
            "project": row["source_project"],
            "repository": owner,
            "event_type": "unknown",
            "control": {
                "version": "control",
                "revision": None,
                "artifact_uri": None,
                "artifact_digest": None,
            },
            "candidate": {
                "version": "candidate",
                "revision": None,
                "artifact_uri": None,
                "artifact_digest": None,
            },
        },
        "downstream_subject": {
            "repository": source_urls[0].split("/issues/")[0]
            if "/issues/" in source_urls[0]
            else source_urls[0],
            "repository_full_name": row["source_project"],
            "revision": "unknown-revision",
            "package": None,
            "test_command_digest": None,
            "source_signal": source_urls[0],
        },
        "environments": {
            "resolution_mode": "unknown",
            "common": {
                "os": "public CI",
                "architecture": "unknown",
                "runner": "unknown",
                "container_digest": None,
                "dependency_snapshot_digest": None,
                "locale": None,
                "timezone": "UTC",
                "network_policy": "unknown",
            },
            "control": {
                "runtime": None,
                "dependency_snapshot_digest": None,
                "variables": {},
                "notes": None,
            },
            "candidate": {
                "runtime": None,
                "dependency_snapshot_digest": None,
                "variables": {},
                "notes": None,
            },
        },
        "outcomes": {
            "control": {
                "status": "unknown" if abstain else "pass",
                "attempts": 0 if abstain else 1,
                "duration_seconds": None,
                "exit_code": None,
                "workflow_run": None,
                "evidence_ids": [source_id],
            },
            "candidate": {
                "status": "unknown" if abstain else "fail",
                "attempts": 0 if abstain else 1,
                "duration_seconds": None,
                "exit_code": None,
                "workflow_run": None,
                "evidence_ids": [source_id],
            },
        },
        "failure": {
            "phase": phase,
            "exception_or_tool": None,
            "message_template": row["observed_failure"],
            "symbol": None,
            "fingerprint": "sha256:" + ("0" * 64),
            "test_identifiers": [],
        },
        "hypotheses": hypotheses,
        "experiments": experiments,
        "evidence": evidence,
        "attribution": {
            "candidate_induced": candidate_induced,
            "responsible_layer": layer,
            "owner_repository": owner,
            "owner_project": row["gold_owner"] if owner else None,
            "intentionality": "unknown",
            "first_bad": None,
            "evidence_tier": row["label_tier"],
            "confidence": "inconclusive" if abstain else "medium",
            "rationale": "Seed-corpus curation record derived from the manifest; full public collection and temporal review remain explicit release evidence requirements.",
        },
        "related_cases": [],
        "resolution": {"status": "unknown"},
        "provenance": {
            "collector": "Radar seed manifest",
            "collector_version": "0.1",
            "collected_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source_snapshot_cutoff": date,
            "workflow_revision": None,
            "attestation_uri": None,
            "record_digest": None,
        },
        "privacy": {
            "visibility": "public",
            "raw_logs_shared": False,
            "source_code_shared": False,
            "redactions": [
                "No raw logs or secrets are included; source URLs are references only."
            ],
        },
    }


def main() -> None:
    target = ROOT / "corpus" / "cases"
    target.mkdir(parents=True, exist_ok=True)
    with (ROOT / "corpus" / "manifest.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            (target / f"{row['case_id']}.json").write_text(
                json.dumps(make_case(row), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
