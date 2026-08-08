"""Canonical failure representation and transparent normalization rules."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from radar_bench.normalize.redaction import redact

_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_HEX_ADDRESS = re.compile(r"\b0x[0-9a-f]{6,}\b", re.IGNORECASE)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][0-9:.+Z-]+\b")
_WIN_PATH = re.compile(r"\b[A-Za-z]:\\[^\s\]\)>,;]+")
_POSIX_PATH = re.compile(r"(?<![\w])/(?:[^\s/]+/)+[^\s]+")
_LINE_COL = re.compile(r"(?::|\bline\s+)\d+(?::\d+)?\b", re.IGNORECASE)
_RUNNER = re.compile(
    r"\b(?:runner|job|run|worker)[-_ ]?(?:id|number)?[=: ]+[A-Za-z0-9_.-]+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NormalizedFailure:
    phase: str
    test_identifiers: tuple[str, ...]
    exception_or_tool: str | None
    message_template: str
    symbols: tuple[str, ...]
    source_format: str
    fingerprint: str
    redacted_excerpt: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["test_identifiers"] = list(self.test_identifiers)
        value["symbols"] = list(self.symbols)
        value["warnings"] = list(self.warnings)
        return value


def normalize_text(
    text: str,
    *,
    source_format: str = "text",
    phase: str = "unknown",
    test_identifiers: list[str] | None = None,
) -> NormalizedFailure:
    original = text or ""
    normalized = _normalize(original)
    exception = _find_exception(original)
    symbols = tuple(
        sorted(set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_.]+\b", normalized)[:50]))
    )
    template = _message_template(normalized)
    canonical = {
        "phase": phase,
        "tests": sorted(test_identifiers or []),
        "exception": exception,
        "message": template,
        "symbols": list(symbols),
        "format": source_format,
    }
    fingerprint = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    warnings = ("empty input",) if not original.strip() else ()
    return NormalizedFailure(
        phase,
        tuple(sorted(test_identifiers or [])),
        exception,
        template,
        symbols,
        source_format,
        fingerprint,
        redact(normalized[:4000]),
        warnings,
    )


def _normalize(text: str) -> str:
    value = _ISO_DATE.sub("<TIMESTAMP>", text)
    value = _UUID.sub("<UUID>", value)
    value = _HEX_ADDRESS.sub("<ADDRESS>", value)
    value = _WIN_PATH.sub("<PATH>", value)
    value = _POSIX_PATH.sub("<PATH>", value)
    value = _RUNNER.sub("<RUNNER>", value)
    value = _LINE_COL.sub(":<LINE>", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _find_exception(text: str) -> str | None:
    match = re.search(
        r"(?:^|\n)([A-Za-z_][\w.]*(?:Error|Exception|Failure|Timeout))(?::|\s|$)", text
    )
    return match.group(1) if match else None


def _message_template(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if not line.startswith(("Traceback", "File ", "E ")):
            return line[:2000]
    return (lines[-1] if lines else "unknown failure")[:2000]
