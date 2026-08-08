"""Typed experiment-plan validation and dry-run rendering."""

from __future__ import annotations

from typing import Any

from radar_bench.errors import ValidationError
from radar_bench.runner.policy import validate_plan_policy
from radar_bench.schema.loader import validate_json


def validate_experiment_plan(plan: dict[str, Any], *, root: Any = None) -> list[str]:
    try:
        validate_json(plan, "experiment", root)
    except ValidationError as exc:
        return exc.errors
    return validate_plan_policy(plan)


def render_experiment_plan(plan: dict[str, Any]) -> str:
    lines = [
        f"DRY RUN: {plan['plan_id']} for {plan['case_id']}",
        f"question: {plan['question']}",
        f"network: {plan['limits']['network_policy']}",
        "commands:",
    ]
    for command in plan["commands"]:
        lines.append("  - " + " ".join(_quote(arg) for arg in command))
    lines.append(f"risk: {plan['risk_classification']}; status: {plan['status']}")
    return "\n".join(lines)


def _quote(value: str) -> str:
    return value if value.replace("-", "").replace("_", "").isalnum() else repr(value)
