"""Conservative redaction for common secret-bearing text patterns."""

from __future__ import annotations

import re

PATTERNS = (
    (
        re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._-]+"),
        r"\1<REDACTED>",
    ),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"), "<REDACTED_GITHUB_TOKEN>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "<REDACTED_API_KEY>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<REDACTED_AWS_KEY>"),
    (
        re.compile(r"(?i)(\b(?:token|secret|password|api[_-]?key)\s*[=:]\s*)[^\s,;]+"),
        r"\1<REDACTED>",
    ),
)


def redact(value: str) -> str:
    for pattern, replacement in PATTERNS:
        value = pattern.sub(replacement, value)
    return value
