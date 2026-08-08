"""Reject unsafe experiment plans before any execution could be considered."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any


def validate_plan_policy(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if plan.get("risk_classification") == "unsafe":
        errors.append("unsafe risk classification is never executable")
    forbidden = {"-c", "-Command", "/c", "-EncodedCommand", "shell-construction"}
    for index, command in enumerate(plan.get("commands", [])):
        if any(argument in forbidden for argument in command):
            errors.append(f"commands[{index}]: shell construction is forbidden")
    for name in plan.get("environment_allowlist", []):
        if (
            name != name.upper()
            or not name.replace("_", "").isalnum()
            or not name[:1].isalpha()
        ):
            errors.append(f"environment_allowlist: invalid variable {name}")
    for output in plan.get("expected_outputs", []):
        if (
            PureWindowsPath(output).is_absolute()
            or PurePosixPath(output).is_absolute()
            or ".." in PurePosixPath(output).parts
            or ".." in PureWindowsPath(output).parts
        ):
            errors.append(f"expected output escapes the scoped directory: {output}")
    limits = plan.get("limits", {})
    if limits.get("network_policy") not in {"denied", "registry_only", "restricted"}:
        errors.append("network policy must be restrictive")
    return errors
