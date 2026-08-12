"""Enforce the preregistered line and branch coverage thresholds separately."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


LINE_THRESHOLD = 90.0
BRANCH_THRESHOLD = 80.0


def _percentage(
    totals: dict[str, Any], covered: str, total: str, preferred: str
) -> float | None:
    value = totals.get(preferred)
    if isinstance(value, (int, float)):
        return float(value)
    numerator = totals.get(covered)
    denominator = totals.get(total)
    if (
        not isinstance(numerator, (int, float))
        or not isinstance(denominator, (int, float))
        or denominator <= 0
    ):
        return None
    return float(numerator) * 100.0 / float(denominator)


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    if len(arguments) != 1:
        print("usage: check_coverage.py COVERAGE_JSON", file=sys.stderr)
        return 2
    try:
        document = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
        totals = document["totals"]
        if not isinstance(totals, dict):
            raise ValueError("coverage totals are not an object")
        line = _percentage(
            totals, "covered_lines", "num_statements", "percent_statements_covered"
        )
        branch = _percentage(
            totals, "covered_branches", "num_branches", "percent_branches_covered"
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": type(exc).__name__}, sort_keys=True))
        return 2
    result = {
        "status": (
            "PASS"
            if line is not None
            and branch is not None
            and line >= LINE_THRESHOLD
            and branch >= BRANCH_THRESHOLD
            else "BLOCKED"
        ),
        "line_percent": round(line, 2) if line is not None else None,
        "branch_percent": round(branch, 2) if branch is not None else None,
        "required": {
            "line_percent": LINE_THRESHOLD,
            "branch_percent": BRANCH_THRESHOLD,
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
