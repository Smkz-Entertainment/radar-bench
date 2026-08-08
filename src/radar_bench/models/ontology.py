"""The v0.3 causal ontology and independent field-level comparison helpers."""

from __future__ import annotations

from typing import Any

ONTOLOGY_FIELDS = (
    "trigger_component",
    "trigger_change",
    "manifestation_project",
    "manifestation_layer",
    "root_cause_component",
    "root_cause_mechanism",
    "action_owner_repository",
    "first_bad_version_or_revision",
    "confounders",
    "evidence_class",
)
EVIDENCE_CLASSES = (
    "OBSERVED",
    "REPRODUCED",
    "CANDIDATE_SPECIFIC",
    "CONFOUNDED",
    "CAUSALLY_SUPPORTED",
    "CONFIRMED",
)


def ontology_errors(value: dict[str, Any]) -> list[str]:
    """Return semantic errors not expressible in the JSON schema."""

    errors: list[str] = []
    if value.get("evidence_class") not in EVIDENCE_CLASSES:
        errors.append("evidence_class is not a v0.3 evidence class")
    if value.get("evidence_class") == "CONFOUNDED" and not value.get("confounders"):
        errors.append("confounded evidence requires at least one confounder")
    if value.get("verdict") == "confounded_change":
        if value.get("candidate_induced") is not None:
            errors.append("confounded_change has no candidate_induced value")
        if value.get("action_owner_repository") is not None:
            errors.append("confounded_change cannot assign an action owner")
    return errors


def field_match(
    prediction: dict[str, Any], label: dict[str, Any], field: str
) -> bool:
    """Compare one ontology field, treating absent optional values as null."""

    return prediction.get(field) == label.get(field)
