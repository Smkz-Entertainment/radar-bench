# v0.6 Benchmark Integrity Challenge

v0.6 is an integrity audit of the bounded v0.5 investigator. It freezes the
v0.5 investigator and the v0.4 corpus, then tests whether the replay channel,
holdout design, and execution claims support a causal-investigation result. It
does not implement a Radar product.

## Frozen scope

The v0.5 investigator implementation digest remains the evaluator-owned value
recorded in `artifacts/v05-result.json`. The v0.6 freeze audit checks that
digest and the last commit touching the investigator/evaluation entry points.
The v0.6 runner does not tune the planner or rewrite v0.5 artifacts.

## Integrity checks

The generated evidence under `artifacts/release-evidence/` covers:

- action-space blindness and response-channel metadata, including status,
  adapters, errors, provenance shape, evidence counts, key order, value types,
  and serialized length;
- incident-, upstream-component-, time-period-, and cross-family-grouped
  holdouts with evaluator-owned deterministic splits and explicit overlap
  checks;
- plausible irrelevant decoy experiments;
- irrelevant counterfactual invariance and control-failure causal sensitivity;
- random, naive, and oracle-availability-only anti-oracle planners;
- the bounded real-execution admission boundary and replay concordance;
- the frozen-investigator digest and v0.6 gate decision.

The gates are fail-closed. `not_evaluable` execution gates do not pass, and a
failed integrity gate is not evidence that the frozen investigator is ready for
product use.

## Current result

The current result is:

- `V06_BENCHMARK_INTEGRITY = FAILED_VALIDATION`;
- `V05_INVESTIGATOR = FROZEN_UNDER_AUDIT`;
- `PRODUCT_IMPLEMENTATION = BLOCKED`;
- decision: `STOP_BENCHMARK_AND_FIX_ORACLE`.

The frozen investigator resolves or abstains correctly on the replay corpus,
but the challenge found three blockers:

1. the replay channel reports `AVAILABLE` alongside `UNAVAILABLE` outcomes on
   40 probes;
2. attribution-case decoys are marked useful at 0.60, above the 0.40 ceiling;
3. the naive first-component planner resolves 0.60, failing the strict
   below-0.60 anti-oracle gate.

The availability-only planner resolves 0.00, so the benchmark is not being
credited for that channel. Its explicit measurement remains important because
the replay oracle reports availability separately from result content.

The corpus also contains no exact environment, command, lockfile, or
secret-free container manifest for the requested 5-10 real executions. The
runner therefore records `BLOCKED_EXTERNAL` and does not fabricate execution
or replay concordance evidence.

The next authorized benchmark step is to repair or replace the replay oracle
and rerun the integrity challenge. Product implementation remains out of scope
until every v0.6 gate passes.
