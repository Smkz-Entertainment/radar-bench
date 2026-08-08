"""Small-sample-safe binomial confidence calculations for release evidence."""

from __future__ import annotations

import math
from typing import Any


def _cdf_at_most(failures: int, trials: int, probability: float) -> float:
    return sum(
        math.comb(trials, index)
        * probability**index
        * (1.0 - probability) ** (trials - index)
        for index in range(failures + 1)
    )


def one_sided_upper_95(failures: int, trials: int) -> float | None:
    """Return an exact one-sided 95% upper bound for a binomial failure rate."""

    if trials <= 0:
        return None
    if failures < 0 or failures > trials:
        raise ValueError("failures must be between zero and trials")
    if failures == 0:
        return float(1.0 - 0.05 ** (1.0 / trials))
    low, high = 0.0, 1.0
    for _ in range(80):
        middle = (low + high) / 2.0
        if _cdf_at_most(failures, trials, middle) > 0.05:
            low = middle
        else:
            high = middle
    return high


def safety_confidence(
    failures: int, trials: int, *, required_trials: int = 300
) -> dict[str, Any]:
    bound = one_sided_upper_95(failures, trials)
    return {
        "failures": failures,
        "trials": trials,
        "observed_failure_rate": failures / trials if trials else None,
        "one_sided_upper_95_failure_rate": bound,
        "zero_failures": failures == 0 and trials > 0,
        "required_trials": required_trials,
        "eligible_for_safety_claim": trials >= required_trials,
        "claim": (
            "eligible only after at least the required independently admitted cases"
            if trials < required_trials
            else "bound is exact one-sided binomial 95%"
        ),
    }
