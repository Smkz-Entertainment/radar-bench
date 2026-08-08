"""Create the non-gold v0.2 admission plan without fabricating cases."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "corpus" / "v0.2"

DISTRIBUTION = [
    ("true_upstream_regression", 25, False),
    ("downstream_incompatibility", 15, False),
    ("dependency_transitive_failure", 15, False),
    ("resolution_artifact_failure", 10, True),
    ("ci_infrastructure_failure", 10, True),
    ("flaky_nondeterministic", 10, True),
    ("expected_breaking_change", 5, True),
    ("ambiguous_inconclusive", 10, True),
]

NEGATIVE_TYPES = [
    "dead_external_url",
    "github_outage",
    "wheel_missing",
    "dns_failure",
    "worker_crash",
    "random_timeout",
    "known_flaky",
    "baseline_broken",
    "resolver_drift",
    "platform_infrastructure",
    "expired_certificate",
    "fixture_disappearance",
    "incorrect_xfail",
]


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    admissions = TARGET / "admissions"
    admissions.mkdir(exist_ok=True)
    rows: list[dict[str, str]] = []
    number = 1
    negative_number = 0
    for category, count, negative in DISTRIBUTION:
        for _ in range(count):
            case_id = f"RADAR-V02-{number:03d}"
            split = (
                "development"
                if number <= 70
                else "validation"
                if number <= 85
                else "hidden_test"
            )
            negative_type = (
                NEGATIVE_TYPES[negative_number % len(NEGATIVE_TYPES)]
                if negative
                else "none"
            )
            if negative:
                negative_number += 1
            record = {
                "schema_version": "0.2",
                "admission_id": f"ADMIT-{case_id}",
                "case_id": case_id,
                "candidate_category": category,
                "negative_control": negative,
                "negative_control_type": negative_type,
                "admission_state": "planned",
                "target_split": split,
                "source_cutoff": "2026-08-08T00:00:00Z",
                "source_urls": [],
                "gold_derivation": "not_started",
                "independent_evidence": [],
                "gold_label": None,
                "audit": {
                    "created_at": "2026-08-08T00:00:00Z",
                    "last_reviewed_at": "2026-08-08T00:00:00Z",
                    "derived_by": "osint_protocol",
                    "review_status": "unreviewed",
                    "reviewer": None,
                },
            }
            (admissions / f"{case_id}.json").write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            rows.append(
                {
                    "admission_id": record["admission_id"],
                    "case_id": case_id,
                    "candidate_category": category,
                    "negative_control": str(negative).lower(),
                    "negative_control_type": negative_type,
                    "target_split": split,
                    "admission_state": "planned",
                    "source_urls": "",
                    "gold_status": "not_admitted",
                }
            )
            number += 1
    with (TARGET / "manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    plan = {
        "protocol_version": "0.2",
        "status": "planning_only",
        "total_target_cases": len(rows),
        "gold_cases_admitted": 0,
        "distribution": {category: count for category, count, _ in DISTRIBUTION},
        "negative_controls": sum(
            count for _, count, negative in DISTRIBUTION if negative
        ),
        "source_urls_collected": 0,
        "gold_labels_created_by_evaluated_agent": 0,
        "next_action": "collect public sources and admit only independently grounded records",
    }
    (TARGET / "plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
