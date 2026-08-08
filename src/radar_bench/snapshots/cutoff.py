"""Fail-closed timestamp and evidence visibility decisions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def parse_cutoff(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("cutoff must include a timezone")
    return parsed.astimezone(UTC)


def visible_before_cutoff(
    evidence: dict[str, Any], cutoff: datetime
) -> tuple[bool, str]:
    if evidence.get("available_before_cutoff") is not True:
        return False, "curator did not attest availability before Tcut"
    value = evidence.get("available_at") or evidence.get("collected_at")
    if not isinstance(value, str):
        return False, "availability timestamp is absent"
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return False, "availability timestamp is invalid"
    if timestamp.tzinfo is None or timestamp.astimezone(UTC) > cutoff:
        return False, "availability is after Tcut or timezone is missing"
    if evidence.get("updated_at"):
        try:
            updated = datetime.fromisoformat(evidence["updated_at"])
            if updated.tzinfo is None or updated.astimezone(UTC) > cutoff:
                return False, "mutable source was updated after Tcut"
        except ValueError:
            return False, "updated_at is invalid"
    return True, "explicitly attested and timestamped no later than Tcut"
