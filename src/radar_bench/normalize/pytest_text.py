"""Pytest text adapter."""

from __future__ import annotations

import re

from radar_bench.normalize.base import NormalizedFailure, normalize_text


def normalize_pytest(text: str) -> NormalizedFailure:
    tests = re.findall(r"(?:FAILED|ERROR)\s+([^\s]+)", text)
    phase = "collection" if "ERROR collecting" in text else "test"
    return normalize_text(
        text, source_format="pytest", phase=phase, test_identifiers=tests
    )
