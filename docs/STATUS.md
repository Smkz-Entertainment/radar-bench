# Status

Radar Bench 1.0 is a viable OSS benchmark and the attribution product thesis is terminated.

## Decisions

- `STATIC_OWNER_ATTRIBUTION = FAILED_VALIDATION`
- `AGENTIC_CAUSAL_INVESTIGATION = FAILED_VALIDATION`
- `CROSS_REPOSITORY_ATTRIBUTION_PRODUCT = TERMINATED`
- `AUTONOMOUS_ATTRIBUTION_MVP = DO_NOT_BUILD`
- `REPLAY_ORACLE_CERTIFICATION = REJECTED`
- `EXECUTABLE_CAUSAL_SAFETY = VALIDATED_SMALL_N`
- `HISTORICAL_ATTRIBUTION_EXECUTABILITY = VALIDATED_SMALL_N`
- `RADAR_BENCH = VIABLE_OSS_PROJECT`

The v0.7 decisive run used five sealed historical cases and twenty opaque safety twins. The frozen investigator abstained safely but resolved only one of five historical positives and missed the required scikit-learn #30512 → SciPy case. That is evidence against the agentic attribution product, not against the executable benchmark.

## Release boundary

The public v1 suite is `decisive-v1`. Canonical execution is a Linux/x86-64 Docker engine with network denial; Docker Desktop's Linux engine is valid even when the client host is Windows or macOS. A clean checkout without externally supplied historical wheelhouses must report `ARTIFACT_UNAVAILABLE`, and an engine that is not Linux/x86-64 must report `PLATFORM_UNAVAILABLE`. Neither condition is a pass.

The v0.1–v0.7 source, schemas, case-sealing records, and negative evidence remain preserved for research history. See [RESEARCH_HISTORY.md](RESEARCH_HISTORY.md).
