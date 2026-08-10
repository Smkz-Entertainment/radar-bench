"""Small dependency-free JSON Schema 2020-12 subset used by Radar.

The schemas in this repository intentionally use a conservative subset. Keeping
the validator in-process makes local evidence checks work without downloading
packages and avoids accepting provider output through a permissive fallback.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse


def _type_ok(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def _resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"external schema reference is not allowed: {ref}")
    current: Any = root
    for part in ref[2:].split("/"):
        current = current[part.replace("~1", "/").replace("~0", "~")]
    if not isinstance(current, dict):
        raise TypeError(f"schema reference is not an object: {ref}")
    return current


def _format_ok(value: str, fmt: str) -> bool:
    if fmt == "date-time":
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.tzinfo is not None
        except ValueError:
            return False
    if fmt == "uri":
        parsed_uri = urlparse(value)
        return bool(
            parsed_uri.scheme
            and (parsed_uri.netloc or parsed_uri.scheme in {"urn", "mailto"})
        )
    return True


def validate(
    instance: Any,
    schema: dict[str, Any],
    *,
    root: dict[str, Any] | None = None,
    path: str = "$",
    errors: list[str] | None = None,
) -> list[str]:
    """Return all validation errors instead of raising on the first one."""
    root = root or schema
    errors = errors if errors is not None else []
    if "$ref" in schema:
        validate(
            instance,
            _resolve(schema["$ref"], root),
            root=root,
            path=path,
            errors=errors,
        )
        return errors
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value is not in enum")
    if "type" in schema:
        expected = (
            schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        )
        if not any(_type_ok(instance, item) for item in expected):
            errors.append(f"{path}: expected type {expected}")
            return errors
    for branch_key in ("oneOf", "anyOf"):
        if branch_key in schema:
            matches = 0
            branch_errors: list[list[str]] = []
            for branch in schema[branch_key]:
                trial: list[str] = []
                validate(instance, branch, root=root, path=path, errors=trial)
                if not trial:
                    matches += 1
                branch_errors.append(trial)
            if (branch_key == "oneOf" and matches != 1) or (
                branch_key == "anyOf" and matches == 0
            ):
                errors.append(
                    f"{path}: {branch_key} failed ({matches} matching branches)"
                )
    if isinstance(instance, dict):
        if len(instance) < schema.get("minProperties", 0):
            errors.append(f"{path}: fewer than minProperties")
        if "maxProperties" in schema and len(instance) > schema["maxProperties"]:
            errors.append(f"{path}: more than maxProperties")
        required = schema.get("required", [])
        for name in required:
            if name not in instance:
                errors.append(f"{path}: missing required property {name!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for name in instance:
                if name not in properties:
                    errors.append(f"{path}: unexpected property {name!r}")
        for name, subschema in properties.items():
            if name in instance:
                validate(
                    instance[name],
                    subschema,
                    root=root,
                    path=f"{path}.{name}",
                    errors=errors,
                )
        if isinstance(schema.get("additionalProperties"), dict):
            for name, value in instance.items():
                if name not in properties:
                    validate(
                        value,
                        schema["additionalProperties"],
                        root=root,
                        path=f"{path}.{name}",
                        errors=errors,
                    )
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than minItems")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: more than maxItems")
        if schema.get("uniqueItems"):
            keys = [repr(item) for item in instance]
            if len(keys) != len(set(keys)):
                errors.append(f"{path}: items must be unique")
        if "items" in schema:
            for index, value in enumerate(instance):
                validate(
                    value,
                    schema["items"],
                    root=root,
                    path=f"{path}[{index}]",
                    errors=errors,
                )
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than minLength")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength")
        if "pattern" in schema and re.fullmatch(schema["pattern"], instance) is None:
            errors.append(f"{path}: does not match pattern")
        if "format" in schema and not _format_ok(instance, schema["format"]):
            errors.append(f"{path}: invalid {schema['format']} format")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: above maximum")
    return errors


def assert_valid(instance: Any, schema: dict[str, Any]) -> None:
    errors = validate(instance, schema)
    if errors:
        from radar_bench.errors import ValidationError

        raise ValidationError("schema validation failed", errors)
