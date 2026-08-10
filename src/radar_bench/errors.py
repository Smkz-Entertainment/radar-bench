"""Stable error types used by the CLI and library."""


class RadarError(Exception):
    """Base class for expected Radar failures."""


class ValidationError(RadarError):
    """A schema, semantic, or policy validation failure."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


class SecurityError(ValidationError):
    """A security policy rejected untrusted input."""


class ExternalBlocked(RadarError):
    """An optional public network operation was blocked or rate limited."""
