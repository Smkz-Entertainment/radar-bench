# Radar Bench v0.7 Executable Investigation Benchmark

v0.7 keeps commit 60ccc18 frozen and replaces historical replay certification with sealed, network-denied execution. It does not implement a product.

## Decision

- Product validation: `BLOCKED_BY_EXECUTABILITY`.
- Agentic causal investigation: `UNVALIDATED`.
- v0.5 investigator: `FROZEN_UNDER_AUDIT`.
- Decision: `BLOCKED_BY_EXECUTABILITY`.

## Preparation boundary

- Status: `BLOCKED_BY_EXECUTABILITY`.
- Cases: `0`.
- Reason: The preparation phase has not sealed any executable cases.

## Gates

- No executable metrics were scored because the sealed corpus is unavailable.

Historical replay remains available for development and qualitative research, but it is not used to certify v0.7. No synthetic execution, gold-mounted runtime, or availability-derived result was substituted.
