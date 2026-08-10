from __future__ import annotations

from radar_bench.schema.validator import validate


def test_schema_validator_handles_types_properties_and_limits() -> None:
    schema = {
        "type": "object",
        "required": ["name", "values"],
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "minLength": 2, "pattern": "^[a-z]+$"},
            "values": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "uniqueItems": True,
                "items": {"type": "integer", "minimum": 0, "maximum": 4},
            },
        },
    }
    errors = validate({"name": "A", "values": [1, 1], "extra": True}, schema)
    assert any("missing" not in error for error in errors)
    assert any("unexpected" in error for error in errors)
    assert any("unique" in error for error in errors)


def test_schema_validator_handles_refs_branches_and_formats() -> None:
    schema = {
        "$defs": {"positive": {"type": "integer", "minimum": 1}},
        "type": "object",
        "properties": {
            "value": {"$ref": "#/$defs/positive"},
            "when": {"type": "string", "format": "date-time"},
            "choice": {
                "oneOf": [{"const": "a"}, {"const": "b"}],
            },
            "optional": {"anyOf": [{"type": "null"}, {"type": "string"}]},
        },
    }
    assert validate(
        {"value": 2, "when": "2026-01-01T00:00:00+00:00", "choice": "a", "optional": None},
        schema,
    ) == []
    errors = validate(
        {"value": 0, "when": "not-a-date", "choice": "c", "optional": 3},
        schema,
    )
    assert len(errors) >= 3


def test_schema_validator_reports_string_numeric_and_array_limits() -> None:
    assert validate("abcdef", {"type": "string", "maxLength": 3})
    assert validate("ABC", {"type": "string", "pattern": "^[a-z]+$"})
    assert validate("not-a-uri", {"type": "string", "format": "uri"})
    assert validate(-1, {"type": "integer", "minimum": 0})
    assert validate(5, {"type": "integer", "maximum": 4})
    assert validate([], {"type": "array", "minItems": 1})
    assert validate([1, 2, 3], {"type": "array", "maxItems": 2})
    assert validate(1, {"type": "string"})
    assert validate("x", {"type": "object"})
    assert validate("x", {"type": "object", "additionalProperties": {"type": "integer"}})
    assert validate({"x": 1}, {"type": "object", "properties": {}, "additionalProperties": {"type": "string"}})
