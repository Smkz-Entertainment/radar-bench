"""Helpers for conservative temporal classification of GitHub records."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def classify_temporal(record: dict[str, Any], cutoff: datetime) -> tuple[str, str]:
    created = _date(record.get("created_at"))
    updated = _date(record.get("updated_at"))
    if created is None:
        return "unknown", "source has no machine-readable creation time"
    if created > cutoff:
        return "post-cutoff", "created after Tcut"
    if updated and updated > cutoff:
        return "temporally-unverifiable", "mutable source was updated after Tcut"
    return "pre-cutoff", "created and last update are no later than Tcut"


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
