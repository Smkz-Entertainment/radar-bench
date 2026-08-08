# Status

v0.1 is frozen as a passing local engineering foundation. v0.2 is a research
milestone and remains partial until an independently grounded corpus clears the
attribution and abstention gates. Planned records do not count as gold.
v0.3 is the Gold Corpus & Blind Attribution milestone; its engineering
contracts pass locally, but its 120 attribution slots and 300 safety slots are
still planned, with zero admitted labels and no hidden evaluation.

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
