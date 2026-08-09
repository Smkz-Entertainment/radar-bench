# Benchmark card

## Purpose

Radar Bench measures whether an investigator can distinguish candidate-induced failures from baseline, packaging, platform, resolver, nondeterministic, and external-resource failures under executable, temporally blind conditions.

## Dataset

`decisive-v1` has 5 sealed historical attribution cases and 20 constructed executable safety twins. The historical cases are pandas #55137, scikit-learn #30512 / SciPy 1.15 RC, pandas #45601, pandas #57124, and pandas #66085. The safety labels are evaluator-only.

## Baselines and metrics

The suite preserves static v0.4, naïve deterministic, and frozen v0.5 lanes. Metrics are reported per lane with denominators: positive resolution 5, candidate-induced correctness 5, action-owner correctness 5, cross-repository resolution 1, semantic ambiguity 1, safety abstention 20, false-owner rate 20, useful experiments 40, and substantive-experiment median.

## Results and claims

The 25-case research run validated small-N executable safety but failed the agentic attribution thesis. It missed the required SciPy-side resolution for #30512. These results are not a population estimate or production-readiness claim.

## Reproducibility

Use `radar-bench validate --suite decisive-v1` and then `radar-bench evaluate --suite decisive-v1`. Canonical execution is Linux/x86-64 Docker only. The repository records the reference result and release audits separately from live observations.
