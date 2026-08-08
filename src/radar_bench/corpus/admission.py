"""Fail-closed admission rules for the independent v0.2 gold corpus."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from radar_bench.errors import ValidationError
from radar_bench.models.case import parse_aware
from radar_bench.schema.loader import validate_json

CATEGORIES = (
    "true_upstream_regression",
    "downstream_incompatibility",
    "dependency_transitive_failure",
    "resolution_artifact_failure",
    "ci_infrastructure_failure",
    "flaky_nondeterministic",
    "expected_breaking_change",
    "ambiguous_inconclusive",
)

LAYERS = {
    "upstream_runtime_or_library",
    "shared_dependency",
    "downstream_project",
    "dependency_resolution",
    "packaging_or_artifact",
    "external_service_or_data",
    "ci_or_infrastructure",
    "flaky_or_nondeterministic",
    "multiple_layers",
    "unknown",
}


def validate_admission(
    record: dict[str, Any], *, root: Path | None = None
) -> list[str]:
    """Return schema and semantic errors without admitting a record implicitly."""

    try:
        validate_json(record, "admission_v02", root)
    except ValidationError as exc:
        return exc.errors
    errors: list[str] = []
    cutoff = parse_aware(record["source_cutoff"], "source_cutoff")
    source_urls = record["source_urls"]
    if len(source_urls) != len(set(source_urls)):
        errors.append("source_urls: URLs must be unique")
    evidence = record["independent_evidence"]
    evidence_ids = [item["evidence_id"] for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        errors.append("independent_evidence: identifiers must be unique")
    for item in evidence:
        published = parse_aware(
            item["published_at"],
            f"independent_evidence[{item['evidence_id']}].published_at",
        )
        if item["available_after_cutoff"] and published <= cutoff:
            errors.append(
                f"{item['evidence_id']}: post-cutoff evidence must be after source_cutoff"
            )
    state = record["admission_state"]
    gold = record.get("gold_label")
    if state == "admitted":
        if record["gold_derivation"] != "independent_public_evidence":
            errors.append("admitted records require independent_public_evidence")
        if record["audit"]["review_status"] != "independently_reviewed":
            errors.append("admitted records require independent review")
        if record["audit"]["derived_by"] not in {"osint_protocol", "human_review"}:
            errors.append("admitted records cannot be derived by a model or provider")
        if not source_urls:
            errors.append("admitted records require public source_urls")
        if not isinstance(gold, dict):
            errors.append("admitted records require a gold_label")
        after_cutoff = [item for item in evidence if item["available_after_cutoff"]]
        if not after_cutoff:
            errors.append("admitted records require post-cutoff independent evidence")
        roles = {item["role"] for item in after_cutoff}
        if "causal" not in roles:
            errors.append("admitted records require post-cutoff causal evidence")
        if "resolution" not in roles and "post_fix" not in roles:
            errors.append("admitted records require resolution or post-fix evidence")
    elif gold is not None:
        errors.append("non-admitted records cannot carry a gold_label")
    if isinstance(gold, dict):
        if gold.get("responsible_layer") not in LAYERS:
            errors.append("gold_label.responsible_layer is not a known layer")
        if record["negative_control"] and not gold.get("should_abstain"):
            errors.append("negative controls must have should_abstain=true")
        if gold.get("confounded") and gold.get("candidate_induced") is not None:
            errors.append("confounded gold labels must leave candidate_induced null")
    if record["negative_control"] and record.get("negative_control_type") == "none":
        errors.append("negative controls require a negative_control_type")
    if not record["negative_control"] and record.get("negative_control_type") != "none":
        errors.append("non-negative records must use negative_control_type=none")
    return errors


def admission_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize planned/admitted material without treating plans as gold."""

    states = Counter(record["admission_state"] for record in records)
    categories = Counter(record["candidate_category"] for record in records)
    admitted = [record for record in records if record["admission_state"] == "admitted"]
    return {
        "records": len(records),
        "states": dict(sorted(states.items())),
        "categories": dict(sorted(categories.items())),
        "admitted_gold": len(admitted),
        "independently_derived": sum(
            record["gold_derivation"] == "independent_public_evidence"
            for record in admitted
        ),
        "planned_is_gold": False,
    }
