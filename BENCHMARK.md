# Benchmark card

## Purpose

Radar Bench measures executable safety and bounded causal-investigation behavior
under a temporally blind interface. It distinguishes candidate-induced failures
from baseline, dependency, packaging, platform, resolver, nondeterministic, and
external-resource failures.

## Current package suite

The current package suite is `decisive-v1.2`: five historical executable cases
and twenty constructed executable safety twins. It uses Docker Linux/x86-64 with
evaluation networking denied. Historical wheelhouses are external,
`RECONSTRUCT_ONLY` inputs. The package version is `1.1.1`; the v1.2 suite
contract remains the immutable `1.1.0` contract so this patch changes no cases,
labels, scoring, or evidence semantics.

`decisive-v1.1` is the preserved corrected historical reference suite. It keeps
the five sealed cases, frozen `v0.4`/`v0.5` baselines, and the canonical negative
result available for regression verification.

## Lanes and scoring

The reference suite runs three immutable lanes:

1. `static-v0.4`
2. `naive-deterministic`
3. `agentic-v0.5-frozen`

The strict result schema records each numerator, denominator, and evaluability
status. Action-owner metrics use eligible labels only. Useful-experiment rate
uses executed attempts. The mandatory case gates are the SciPy-side resolution
for scikit-learn #30512 and unresolved semantic intent for pandas #45601.

The v1.2 evaluator loads gold only after candidate execution. Candidate output
cannot provide case identity, evaluator labels, or post-cutoff evidence. Each run
uses fresh opaque episode IDs and records experiment receipts, cleanup, and
network denial.

## Scientific result and boundary

The preserved small-N evidence validates executable safety and historical runtime
reproduction while rejecting the frozen agentic attribution hypothesis, including
the cross-repository requirement. This is not a population estimate, a hidden
test, a production-readiness claim, or evidence to build an autonomous
attribution service.

## Reproduction

Follow [docs/QUICKSTART.md](docs/QUICKSTART.md) for the release-wheel v1.2
workflow and [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md) for clean-clone
and regression procedures. Missing inputs remain blocked; live execution is
never replaced by the canonical reference result.
