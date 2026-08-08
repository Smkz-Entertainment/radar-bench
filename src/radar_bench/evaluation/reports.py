"""Human and machine report serialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Radar Benchmark Report",
        "",
        "This report is exploratory and does not estimate production accuracy.",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for name, metric in report.get("metrics", {}).items():
        if isinstance(metric, dict) and "value" in metric:
            lines.append(
                f"| {name} | {metric['value']} ({metric.get('numerator')}/{metric.get('denominator')}) |"
            )
    return "\n".join(lines) + "\n"
