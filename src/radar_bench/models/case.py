"""RegressionCase semantic validation beyond JSON Schema."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from radar_bench.errors import ValidationError
from radar_bench.schema.loader import validate_json


def parse_aware(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{field}: invalid date-time") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field}: timezone is required")
    return parsed


def _unique(values: list[str], label: str, errors: list[str]) -> None:
    if len(values) != len(set(values)):
        errors.append(f"{label}: identifiers must be unique")


def validate_case(
    case: dict[str, Any], *, root: Path | None = None, strict: bool = False
) -> list[str]:
    """Return semantic errors; schema errors are included in the result."""
    errors: list[str] = []
    try:
        validate_json(case, "case", root)
    except ValidationError as exc:
        errors.extend(exc.errors)
        return errors
    evidence = case.get("evidence", [])
    evidence_ids = [item["evidence_id"] for item in evidence]
    _unique(evidence_ids, "evidence", errors)
    experiments = case.get("experiments", [])
    experiment_ids = [item["experiment_id"] for item in experiments]
    _unique(experiment_ids, "experiments", errors)
    hypotheses = case.get("hypotheses", [])
    hypothesis_ids = [item["hypothesis_id"] for item in hypotheses]
    _unique(hypothesis_ids, "hypotheses", errors)
    evidence_set = set(evidence_ids)
    experiment_set = set(experiment_ids)
    for place, refs, target in _reference_lists(case, evidence_set, experiment_set):
        for ref in refs:
            if ref not in target:
                errors.append(f"{place}: unknown reference {ref}")
    cutoff = parse_aware(
        case["provenance"]["source_snapshot_cutoff"],
        "provenance.source_snapshot_cutoff",
    )
    for item in evidence:
        collected = parse_aware(
            item["collected_at"], f"evidence[{item['evidence_id']}].collected_at"
        )
        if item.get("available_before_cutoff") is True and collected > cutoff:
            errors.append(
                f"{item['evidence_id']}: available_before_cutoff conflicts with collected_at"
            )
        if item.get("available_before_cutoff") is False and strict:
            # Full curated records may include gold evidence; strict applies to input records.
            pass
        digest = item.get("digest")
        if digest and not digest.startswith("sha256:"):
            errors.append(f"{item['evidence_id']}: invalid digest")
    lifecycle = case["lifecycle"]
    observed = parse_aware(lifecycle["observed_at"], "lifecycle.observed_at")
    updated = parse_aware(lifecycle["updated_at"], "lifecycle.updated_at")
    if updated < observed:
        errors.append("lifecycle.updated_at precedes observed_at")
    if lifecycle.get("closed_at"):
        closed = parse_aware(lifecycle["closed_at"], "lifecycle.closed_at")
        if closed < updated:
            errors.append("lifecycle.closed_at precedes updated_at")
    attribution = case["attribution"]
    if attribution["confidence"] in {"confirmed", "high"}:
        supported = any(
            item.get("status") == "supported" and item.get("evidence_ids")
            for item in experiments
        )
        if not supported and not any(
            item.get("kind") == "maintainer_confirmation" for item in evidence
        ):
            errors.append(
                "high/confirmed attribution requires supporting experiment or maintainer evidence"
            )
    if (
        case["lifecycle"]["state"] == "retracted"
        and attribution["evidence_tier"] != "UNLABELED"
    ):
        errors.append("retracted cases cannot remain benchmark gold")
    if strict and any(
        item.get("available_before_cutoff") is False for item in evidence
    ):
        errors.append(
            "post-cutoff evidence is not permitted in an inference-visible case"
        )
    return errors


def _reference_lists(
    case: dict[str, Any], evidence_set: set[str], experiment_set: set[str]
) -> Iterator[tuple[str, list[str], set[str]]]:
    for section in (case.get("experiments", []), case.get("hypotheses", [])):
        for item in section:
            yield (
                f"{item.get('experiment_id', item.get('hypothesis_id'))}.evidence_ids",
                item.get("evidence_ids", []),
                evidence_set,
            )
            if "experiment_ids" in item:
                yield (
                    f"{item.get('hypothesis_id')}.experiment_ids",
                    item["experiment_ids"],
                    experiment_set,
                )
    for outcome_name, outcome in case.get("outcomes", {}).items():
        yield (
            f"outcomes.{outcome_name}.evidence_ids",
            outcome.get("evidence_ids", []),
            evidence_set,
        )


def content_digest(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()
