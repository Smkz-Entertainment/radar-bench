"""v0.4 resolution-chain admission and pilot-stage gates."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from radar_bench.errors import ValidationError
from radar_bench.models.case import parse_aware
from radar_bench.schema.loader import validate_json

REJECTION_REASONS = (
    "NO_INDEPENDENT_CONFIRMATION",
    "NO_TEMPORAL_BOUNDARY",
    "MISSING_CONTROL",
    "AMBIGUOUS_OWNER",
    "BROKEN_EXTERNAL_ARTIFACT",
    "SOURCE_UNAVAILABLE",
    "DUPLICATE_INCIDENT",
    "INSUFFICIENT_RESOLUTION_EVIDENCE",
)
GOLD_A_ROLES = {
    "upstream_confirmation",
    "first_bad",
    "causal_intervention",
    "reproducer",
    "resolution",
    "post_fix_recovery",
}


def validate_v04_record(record: dict[str, Any], *, root: Path | None = None) -> list[str]:
    try:
        validate_json(record, "admission_v04", root)
    except ValidationError as exc:
        return exc.errors
    errors: list[str] = []
    cutoff = parse_aware(record["source_cutoff"], "source_cutoff")
    t0 = parse_aware(record["t0"], "t0")
    if cutoff < t0:
        errors.append("source_cutoff must not precede t0")
    state = record["admission_state"]
    source_urls = [item["uri"] for item in record["source_chain"]]
    evidence_ids = [item["evidence_id"] for item in record["source_chain"]]
    if len(evidence_ids) != len(set(evidence_ids)):
        errors.append("source_chain evidence_ids must be unique")
    snapshot_urls = {item["uri"] for item in record["source_snapshots"]}
    missing_snapshots = set(source_urls) - snapshot_urls
    if missing_snapshots:
        errors.append("source_chain URLs missing fetched snapshots")
    for item in record["source_chain"]:
        published = parse_aware(item["published_at"], f"{item['evidence_id']}.published_at")
        if published < t0:
            errors.append(f"{item['evidence_id']} precedes t0")
        if item["available_after_cutoff"] and published <= cutoff:
            errors.append(f"{item['evidence_id']} is not after source_cutoff")
        if item["snapshot_digest"] is None and state not in {"blocked", "rejected"}:
            errors.append(f"{item['evidence_id']} has no immutable digest")
    label = record.get("label")
    if state == "admitted":
        if record["rejection_reason"] is not None:
            errors.append("admitted records cannot have a rejection reason")
        if record["audit"]["review_status"] != "independently_reviewed":
            errors.append("admitted records require independent review")
        if record["gold_level"] is None or label is None:
            errors.append("admitted records require a gold level and label")
        roles = {
            item["role"]
            for item in record["source_chain"]
            if item["available_after_cutoff"]
        }
        if record["gold_level"] == "Gold-A":
            missing = sorted(GOLD_A_ROLES - roles)
            if missing:
                errors.append("Gold-A missing roles: " + ", ".join(missing))
            if not label or not label["action_owner_scored"]:
                errors.append("Gold-A must be included in action-owner scoring")
        if record["gold_level"] == "Gold-B" and label and label["action_owner_scored"]:
            errors.append("Gold-B cannot enter strict action-owner scoring")
        if record["corpus_kind"] == "safety":
            if record["gold_level"] != "Safety-A" or not label or not label["should_abstain"]:
                errors.append("admitted safety records require Safety-A abstention labels")
        if not record["candidate_snapshot"]["cutoff_only"]:
            errors.append("candidate snapshot must be cutoff-only")
        if not record["gold_packet"]["post_cutoff_only"] or not record["gold_packet"]["scorer_only"]:
            errors.append("gold packet must be post-cutoff and scorer-only")
    elif state == "rejected":
        if record["rejection_reason"] is None:
            errors.append("rejected records require a rejection reason")
        if label is not None or record["gold_level"] is not None:
            errors.append("rejected records cannot carry labels")
    elif state == "blocked":
        if record["rejection_reason"] not in {"SOURCE_UNAVAILABLE", "NO_TEMPORAL_BOUNDARY"}:
            errors.append("blocked records require a source or temporal blocker")
    elif label is not None:
        errors.append("non-admitted records cannot carry labels")
    if record["negative_control"] and record["corpus_kind"] != "safety":
        errors.append("negative controls belong to the safety corpus")
    if record["corpus_kind"] == "safety" and not record["negative_control"]:
        errors.append("safety records must be negative controls")
    if record["rejection_reason"] is not None and record["rejection_reason"] not in REJECTION_REASONS:
        errors.append("unknown rejection reason")
    return errors


def validate_v04_records(records: list[dict[str, Any]], *, root: Path | None = None) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for record in records:
        identifier = record.get("record_id", "missing-record-id")
        if identifier in seen:
            errors.append(f"{identifier}: duplicate record_id")
        seen.add(identifier)
        errors.extend(f"{identifier}: {error}" for error in validate_v04_record(record, root=root))
    return errors


def v04_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    admitted = [item for item in records if item["admission_state"] == "admitted"]
    attribution = [item for item in admitted if item["corpus_kind"] == "attribution"]
    safety = [item for item in admitted if item["corpus_kind"] == "safety"]
    return {
        "records_examined": len(records),
        "admitted_attribution": len(attribution),
        "admitted_safety": len(safety),
        "gold_levels": dict(sorted(Counter(item["gold_level"] for item in admitted).items())),
        "states": dict(sorted(Counter(item["admission_state"] for item in records).items())),
        "categories": dict(sorted(Counter(item["candidate_category"] for item in records).items())),
        "difficulty": dict(sorted(Counter(item["difficulty"] for item in admitted).items())),
        "rejection_reasons": dict(sorted(Counter(item["rejection_reason"] for item in records if item["rejection_reason"]).items())),
        "pilot_targets": {"attribution": 20, "safety": 40},
        "pilot_success": len(attribution) >= 20 and len(safety) >= 40,
        "rejection_is_not_failure_metric": True,
    }


def v04_early_gates(report: dict[str, Any]) -> dict[str, Any]:
    """Apply the pilot continuation thresholds, separate from product gates."""

    metrics = report.get("metrics", {})
    checks = {
        "action_owner_precision": (metrics.get("action_owner", {}).get("precision", {}).get("value"), 0.70),
        "candidate_induced_precision": (metrics.get("candidate_induction", {}).get("precision", {}).get("value"), 0.80),
        "abstention_recall": (metrics.get("abstention", {}).get("recall", {}).get("value"), 0.90),
        "false_high_confidence_upstream": (
            metrics.get("false_high_confidence_upstream", {}).get("failures"),
            0,
        ),
    }
    rendered: dict[str, Any] = {}
    for name, (value, threshold) in checks.items():
        if value is None:
            status = "not_evaluable"
        elif name == "false_high_confidence_upstream":
            status = "pass" if value == threshold else "fail"
        else:
            status = "pass" if value >= threshold else "fail"
        rendered[name] = {"value": value, "threshold": threshold, "status": status}
    continuation = all(item["status"] == "pass" for item in rendered.values())
    return {
        "stage": "pilot-20-40",
        "checks": rendered,
        "continue_mining": continuation,
        "interpretation": "These are worth-continuing thresholds, not production gates.",
    }
