"""Load repository-owned JSON schemas and validate JSON documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from radar_bench.config import schema_root
from radar_bench.schema.validator import assert_valid

SCHEMAS = {
    "investigation_episode_v01": "investigation-episode-v0.1.schema.json",
    "investigation_experiment_v01": "investigation-experiment-v0.1.schema.json",
    "decisive_suite_v1_1": "decisive-suite-v1.1.schema.json",
    "benchmark_result_v1_1": "benchmark-result-v1.1.schema.json",
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
