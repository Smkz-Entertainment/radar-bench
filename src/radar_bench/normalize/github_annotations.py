"""GitHub annotation/check metadata adapter."""

from __future__ import annotations

from typing import Any

from radar_bench.normalize.base import NormalizedFailure, normalize_text


def normalize_annotations(
    value: dict[str, Any] | list[dict[str, Any]],
) -> NormalizedFailure:
    annotations = value if isinstance(value, list) else value.get("annotations", [])
    text = "\n".join(str(item.get("message", "")) for item in annotations)
    tests = [str(item.get("path", "")) for item in annotations if item.get("path")]
    return normalize_text(
        text, source_format="github", phase="test", test_identifiers=tests
    )
