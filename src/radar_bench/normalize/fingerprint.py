"""Public fingerprint helper."""

from radar_bench.normalize.base import normalize_text


def fingerprint(
    text: str, *, source_format: str = "text", phase: str = "unknown"
) -> str:
    return normalize_text(text, source_format=source_format, phase=phase).fingerprint
