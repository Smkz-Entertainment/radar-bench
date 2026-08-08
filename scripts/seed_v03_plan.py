"""Create the v0.3 two-corpus research plan without fabricating gold."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "corpus" / "v0.3"
CUTOFF = "2026-08-09T00:00:00Z"
NOW = datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _record(
    number: int,
    *,
    kind: str,
    category: str,
    difficulty: str,
    negative: bool,
    negative_type: str,
    counterfactual: bool = False,
    source_case: str | None = None,
) -> dict:
    case_id = f"RADAR-V03-{kind[:3].upper()}-{number:04d}"
    return {
        "schema_version": "0.3",
        "admission_id": f"ADMIT-V03-{number:04d}",
        "case_id": case_id,
        "corpus_kind": "attribution_gold" if kind == "GOLD" else "safety_abstention",
        "candidate_category": category,
        "difficulty": difficulty,
        "negative_control": negative,
        "negative_control_type": negative_type,
        "counterfactual": counterfactual,
        "derived_from_positive_case_id": source_case,
        "admission_state": "planned",
        "target_split": "hidden_test",
        "source_cutoff": CUTOFF,
        "source_urls": [],
        "independent_evidence": [],
        "candidate_snapshot": {"path": None, "digest": None, "cutoff_only": True},
        "gold_packet": {
            "path": None,
            "digest": None,
            "post_cutoff_only": True,
            "scorer_only": True,
        },
        "gold_derivation": "not_started",
        "gold_label": None,
        "audit": {
            "created_at": NOW,
            "last_reviewed_at": NOW,
            "derived_by": "osint_protocol",
            "review_status": "unreviewed",
            "reviewer": None,
            "record_digest": None,
        },
    }


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _write_manifest(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["case_id", "candidate_category", "difficulty", "admission_state", "counterfactual"])
        writer.writerows(
            [
                [
                    record["case_id"],
                    record["candidate_category"],
                    record["difficulty"],
                    record["admission_state"],
                    str(record["counterfactual"]).lower(),
                ]
                for record in records
            ]
        )


def main() -> None:
    categories = [
        ("true_upstream_regression", 20),
        ("expected_breaking_change", 20),
        ("downstream_incompatibility", 20),
        ("dependency_transitive_failure", 20),
        ("packaging_build_failure", 15),
        ("resolver_failure", 15),
        ("cross_repo_system_failure", 10),
    ]
    attribution: list[dict] = []
    number = 1
    for category, count in categories:
        for _ in range(count):
            attribution.append(
                _record(
                    number,
                    kind="GOLD",
                    category=category,
                    difficulty=f"D{((len(attribution)) % 5) + 1}",
                    negative=False,
                    negative_type="none",
                )
            )
            number += 1

    safety_plan = [
        ("negative_control", 20, "unsafe_to_attribute"),
        ("confounded_change", 30, "confounded"),
        ("flaky_nondeterministic", 30, "flaky"),
        ("infrastructure_failure", 30, "infrastructure"),
        ("baseline_broken", 30, "baseline_broken"),
        ("duplicate", 25, "duplicate"),
        ("artifact_missing", 25, "artifact_missing"),
        ("resolver_confounded", 25, "resolver_confounded"),
        ("unsafe_to_attribute", 35, "unsafe_to_attribute"),
        ("counterfactual_variant", 50, "counterfactual"),
    ]
    safety: list[dict] = []
    safety_number = 1
    for category, count, negative_type in safety_plan:
        for _ in range(count):
            is_counterfactual = category == "counterfactual_variant"
            source = attribution[(safety_number - 1) % len(attribution)]["case_id"] if is_counterfactual else None
            safety.append(
                _record(
                    1000 + safety_number,
                    kind="SAFE",
                    category=category,
                    difficulty=f"D{((len(safety)) % 5) + 1}",
                    negative=True,
                    negative_type=negative_type,
                    counterfactual=is_counterfactual,
                    source_case=source,
                )
            )
            safety_number += 1

    attribution_root = TARGET / "attribution-gold" / "admissions"
    safety_root = TARGET / "safety-abstention" / "admissions"
    counterfactual_root = TARGET / "safety-abstention" / "counterfactuals"
    for record in attribution:
        _write_json(attribution_root / f"{record['case_id']}.json", record)
    for record in safety:
        destination = counterfactual_root if record["counterfactual"] else safety_root
        _write_json(destination / f"{record['case_id']}.json", record)
    _write_manifest(TARGET / "attribution-gold" / "manifest.csv", attribution)
    _write_manifest(TARGET / "safety-abstention" / "manifest.csv", safety)
    _write_json(
        TARGET / "plan.json",
        {
            "schema_version": "0.3",
            "plan_id": "RADAR-V03-GOLD-AND-SAFETY",
            "source_cutoff": CUTOFF,
            "attribution_gold_target": 120,
            "safety_abstention_target": 300,
            "counterfactual_minimum": 50,
            "difficulty_tiers": ["D1", "D2", "D3", "D4", "D5"],
            "attribution_categories": {key: value for key, value in categories},
            "safety_categories": {key: value for key, value, _ in safety_plan},
            "records_are_plans_not_gold": True,
            "admission_policy": "gold-admission-v0.3.schema.json plus validate_gold_admission",
            "corpus_counts": {
                "attribution_gold_planned": len(attribution),
                "safety_abstention_planned": len(safety),
                "counterfactual_variants_planned": sum(item["counterfactual"] for item in safety),
            },
        },
    )
    (TARGET / "README.md").write_text(
        "# Radar Bench v0.3 corpora\n\n"
        "These are curation plans, not gold labels. Admission is fail-closed and requires independent post-cutoff public evidence, immutable snapshots, and human or OSINT review. Planned records must never be scored as gold. Counterfactual variants are safety cases and do not inherit their source positive label.\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"attribution": len(attribution), "safety": len(safety), "counterfactuals": sum(item["counterfactual"] for item in safety)}, sort_keys=True))


if __name__ == "__main__":
    main()
