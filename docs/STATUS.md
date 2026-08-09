# Status

v0.1 is frozen as a passing local engineering foundation. v0.2 is a research
milestone and remains partial until an independently grounded corpus clears the
attribution and abstention gates. Planned records do not count as gold.
v0.3 is the Gold Corpus & Blind Attribution milestone; its engineering
contracts pass locally, but its 120 attribution slots and 300 safety slots are
still planned, with zero admitted labels and no hidden evaluation.
v0.4 is the Gold Corpus Mining & Admission pilot. It has 20 admitted
attribution records and 40 admitted safety records with five explicit temporal
blocks. The corpus denominator is valid, but deterministic continuation gates
fail on candidate-induced precision (0.60) and action-owner precision (0.00),
so the result is `PIVOT_REQUIRED`, not a capability or production claim.
v0.5 is the bounded Interactive Regression Investigation pilot over the frozen
v0.4 records. It preserves the v0.4 result as
`STATIC_OWNER_ATTRIBUTION = FAILED_VALIDATION`; its deterministic replay-first
heuristic lane currently clears the frozen continuation thresholds, so
`AGENTIC_CAUSAL_INVESTIGATION = ACTIVE_VALIDATED`. This is not production
readiness and does not authorize corpus or product expansion.
v0.6 is the Benchmark Integrity Challenge over that frozen v0.5 investigator.
It currently reports `V06_BENCHMARK_INTEGRITY = FAILED_VALIDATION`, keeps
`V05_INVESTIGATOR = FROZEN_UNDER_AUDIT`, and blocks product implementation.
The replay channel has status/result mismatches, attribution decoys are marked
useful too often, the naive planner meets the strict failure boundary, and no
exact environment manifest exists for real execution. See
[V06_BENCHMARK_INTEGRITY.md](V06_BENCHMARK_INTEGRITY.md).

## Decisions

- Runtime dependencies are empty in v0.1 so schema, temporal, and safety checks
  remain runnable offline.
- The standard-library HTTP client is read-only and rejects non-GitHub hosts.
- Gold evidence is stored separately and inference loaders refuse gold paths.
- Unsupported attributions abstain instead of guessing an owner.
- `confounded_change` is a v0.2 abstention outcome when candidate and control
  differ but runtime, dependency, resolver, or environment variables also
  changed.
- Evidence classes are ordered `OBSERVED`, `REPRODUCED`,
  `CAUSALLY_SUPPORTED`, `CONFIRMED`; numeric confidence is accompanied by
  calibration evidence.

## Known limitations

- Public GitHub collection depends on network/rate-limit availability.
- The seed manifest is a curation queue; only the worked OpenBLAS record is a
  complete reference case in this local foundation.
- The custom validator deliberately implements the repository's JSON Schema
  subset; external schema-hosting and production-scale corpus expansion remain
  future work.
- The v0.2 corpus has 100 planned admission slots and zero admitted gold cases.
- Local-model and Codex lanes have accounting and comparison contracts, but no
  provider is credited with incremental value until the same hidden cases are
  scored and costed across all lanes.
- v0.3 adds D1-D5 difficulty, separate causal ontology fields, exact safety
  confidence bounds, and a portable candidate-only blind boundary. It does not
  claim an OS sandbox for arbitrary native third-party code.
- v0.4 adds resolution-chain admission, Gold-A/Gold-B/Safety-A levels, explicit
  rejection taxonomy, content-addressed public snapshots, and pilot
  continuation gates. Codex and local-model lanes are intentionally not run.
- v0.5 adds evaluator-owned InvestigationEpisode and experiment schemas,
  temporal-blind candidate views, bounded replay, state-machine ledgers,
  attributability classes, Resolution@k, safety, ablation, and kill-gate
  evidence. Real container execution and optional model lanes remain blocked
  when no safe runtime or no-cost/credentialed model is available.
- v0.6 adds evaluator-owned integrity audits for the oracle channel, grouped
  holdouts, decoys, counterfactuals, anti-oracle baselines, and freeze
  verification. Its failed gates prevent productization until the oracle is
  repaired and the challenge passes.
