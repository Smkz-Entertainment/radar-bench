# Benchmark card

## Purpose

Radar Bench measures executable safety and bounded causal-investigation
behavior under a sealed, temporally blind interface. It distinguishes
candidate-induced failures from baseline, dependency, packaging, platform,
resolver, nondeterministic, and external-resource failures.

## Canonical suite

decisive-v1.1 contains five historical executable attribution cases and twenty
constructed executable safety twins. The required engine is Docker Linux/x86-64
with evaluation networking denied. Historical wheelhouses are external
RECONSTRUCT_ONLY inputs.

## Lanes and scoring

The suite runs three immutable lanes:

1. static-v0.4
2. naive-deterministic
3. agentic-v0.5-frozen

The strict result schema records every numerator and denominator. Action-owner
metrics use eligible labels only. Useful-experiment rate uses executed
attempts. The SciPy-side resolution for scikit-learn #30512 and the semantic
ambiguity gate for pandas #45601 are mandatory case-level gates.

An evaluator-side metadata-only audit projects candidate-visible safety-view
fields while removing case identity, paths, digests, and gold labels. All
twenty projections are identical; the resulting family inference is prior-only
(20% majority prior versus 16.67% six-way uniform chance).

## Claims

The small executable safety and historical-runtime evidence is preserved.
The frozen agentic attribution hypothesis failed validation, including the
cross-repository requirement. This is not a population estimate, a production
readiness claim, or evidence to build an autonomous attribution service.

## Reproduction

See docs/QUICKSTART.md and docs/REPRODUCIBILITY.md. The reference result is
evaluator evidence only and can never substitute for live execution.

## v1.2 release-candidate contract

`decisive-v1.2` is a new immutable suite identity for the corrected information
and protocol contract. The candidate bundle contains only T-cut evidence and
runtime capabilities. Gold labels, provenance, scoring eligibility, and case
mapping are evaluator-only. Each invocation receives fresh random episode IDs;
the evaluator canonicalizes returned order and rejects case IDs or gold fields
from candidate output. The suite remains blocked until historical runtimes and
the external candidate harness reproduce the evidence in a clean clone.
