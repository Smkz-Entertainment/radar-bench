"""Fail-closed v0.3 gold and safety admission rules."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from radar_bench.errors import ValidationError
from radar_bench.models.case import parse_aware
from radar_bench.schema.loader import validate_json

REQUIRED_HIGH_CONFIDENCE_ROLES = {
    "maintainer_confirmation",
    "first_bad",
    "causal",
    "reproducer",
    "resolution",
    "post_fix",
}
ADMITTED_KINDS = {"attribution_gold", "safety_abstention"}


def validate_gold_admission(
    record: dict[str, Any], *, root: Path | None = None
) -> list[str]:
    """Validate a record and reject labels without a complete evidence packet."""

    try:
        validate_json(record, "admission_v03", root)
    except ValidationError as exc:
        return exc.errors
    errors: list[str] = []
    cutoff = parse_aware(record["source_cutoff"], "source_cutoff")
    evidence = record["independent_evidence"]
    evidence_ids = [item["evidence_id"] for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        errors.append("independent_evidence identifiers must be unique")
    urls = record["source_urls"]
    if len(urls) != len(set(urls)):
        errors.append("source_urls must be unique")
    for item in evidence:
        published = parse_aware(
            item["published_at"], f"{item['evidence_id']}.published_at"
        )
        if item["available_after_cutoff"] and published <= cutoff:
            errors.append(f"{item['evidence_id']} is not after source_cutoff")
        if item["available_after_cutoff"] and not item["snapshot_digest"]:
            errors.append(f"{item['evidence_id']} lacks an immutable snapshot digest")
    kind = record["corpus_kind"]
    negative = record["negative_control"]
    if kind == "attribution_gold" and negative:
        errors.append("attribution_gold records cannot be negative controls")
    if kind == "safety_abstention" and not negative:
        errors.append("safety_abstention records must be negative controls")
    if record["counterfactual"]:
        if kind != "safety_abstention":
            errors.append("counterfactual variants belong to safety_abstention")
        if not record["derived_from_positive_case_id"]:
            errors.append("counterfactual variants require a positive source case id")
        if record.get("gold_label") is not None and record["gold_derivation"] != (
            "independent_public_evidence"
        ):
            errors.append("counterfactual labels require their own independent evidence")
    if record["negative_control"] and record["negative_control_type"] == "none":
        errors.append("negative controls require a negative_control_type")
    if not record["negative_control"] and record["negative_control_type"] != "none":
        errors.append("positive records must use negative_control_type=none")
    state = record["admission_state"]
    label = record.get("gold_label")
    if state == "admitted":
        if record["gold_derivation"] != "independent_public_evidence":
            errors.append("admitted records require independent_public_evidence")
        if record["audit"]["review_status"] != "independently_reviewed":
            errors.append("admitted records require independent review")
        if record["audit"]["derived_by"] not in {"osint_protocol", "human_review"}:
            errors.append("admitted records cannot be derived by a provider")
        if not urls:
            errors.append("admitted records require public source_urls")
        if not isinstance(label, dict):
            errors.append("admitted records require a gold_label")
        after_cutoff = [item for item in evidence if item["available_after_cutoff"]]
        roles = {item["role"] for item in after_cutoff}
        missing = sorted(REQUIRED_HIGH_CONFIDENCE_ROLES - roles)
        if missing:
            errors.append("admitted records lack required evidence roles: " + ", ".join(missing))
        if not record["candidate_snapshot"]["path"] or not record["gold_packet"]["path"]:
            errors.append("admitted records require physically separate snapshot paths")
        if not record["candidate_snapshot"]["digest"] or not record["gold_packet"]["digest"]:
            errors.append("admitted records require immutable candidate and gold digests")
        if not record["candidate_snapshot"]["cutoff_only"]:
            errors.append("candidate snapshot must be cutoff-only")
        if not record["gold_packet"]["post_cutoff_only"] or not record["gold_packet"]["scorer_only"]:
            errors.append("gold packet must be post-cutoff and scorer-only")
    elif label is not None:
        errors.append("non-admitted records cannot carry a gold_label")
    if isinstance(label, dict):
        if record["negative_control"] and not label["should_abstain"]:
            errors.append("negative controls must have should_abstain=true")
        if label["evidence_class"] == "CONFOUNDED" and label["candidate_induced"] is not None:
            errors.append("confounded labels must leave candidate_induced null")
    return errors


def validate_v03_records(records: list[dict[str, Any]], *, root: Path | None = None) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        case_id = record.get("case_id", f"index-{index}")
        if case_id in seen:
            errors.append(f"{case_id}: duplicate case_id")
        seen.add(case_id)
        errors.extend(f"{case_id}: {error}" for error in validate_gold_admission(record, root=root))
    return errors


def v03_corpus_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    attribution = [item for item in records if item["corpus_kind"] == "attribution_gold"]
    safety = [item for item in records if item["corpus_kind"] == "safety_abstention"]
    admitted = [item for item in records if item["admission_state"] == "admitted"]
    return {
        "records": len(records),
        "attribution_gold": len(attribution),
        "safety_abstention": len(safety),
        "states": dict(sorted(Counter(item["admission_state"] for item in records).items())),
        "attribution_categories": dict(sorted(Counter(item["candidate_category"] for item in attribution).items())),
        "attribution_difficulty": dict(sorted(Counter(item["difficulty"] for item in attribution).items())),
        "safety_categories": dict(sorted(Counter(item["candidate_category"] for item in safety).items())),
        "counterfactual_variants": sum(item["counterfactual"] for item in safety),
        "admitted_gold": len(admitted),
        "independent_high_confidence_admitted": sum(
            item["gold_derivation"] == "independent_public_evidence" for item in admitted
        ),
        "planned_is_gold": False,
        "sufficient_for_safety_claim": len(
            [item for item in safety if item["admission_state"] == "admitted"]
        ) >= 300,
    }
