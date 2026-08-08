"""Load repository-owned JSON schemas and validate JSON documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from radar_bench.config import schema_root
from radar_bench.schema.validator import assert_valid

SCHEMAS = {
    "case": "regression-case-v0.1.schema.json",
    "prediction": "prediction-v0.1.schema.json",
    "prediction_v02": "prediction-v0.2.schema.json",
    "experiment": "experiment-plan-v0.1.schema.json",
    "admission_v02": "corpus-admission-v0.2.schema.json",
    "ablation_v02": "ablation-record-v0.2.schema.json",
}


def load_schema(kind: str, root: Path | None = None) -> dict[str, Any]:
    try:
        filename = SCHEMAS[kind]
    except KeyError as exc:
        raise ValueError(f"unknown schema kind: {kind}") from exc
    with (schema_root(root) / filename).open(encoding="utf-8") as handle:
        return cast(dict[str, Any], json.load(handle))


def validate_json(document: Any, kind: str, root: Path | None = None) -> None:
    assert_valid(document, load_schema(kind, root))
