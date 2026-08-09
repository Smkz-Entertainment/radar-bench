# Radar Bench 1.0.0 release evidence

Release readiness: **BLOCKED**

This bundle records the v1 OSS benchmark boundary. It does not convert a blocked runtime into a benchmark score and does not claim product or production validation.

## Scientific decision

- `EXECUTABLE_CAUSAL_SAFETY = VALIDATED_SMALL_N`
- `HISTORICAL_ATTRIBUTION_EXECUTABILITY = VALIDATED_SMALL_N`
- `AGENTIC_CAUSAL_INVESTIGATION = FAILED_VALIDATION`
- `CROSS_REPOSITORY_ATTRIBUTION_PRODUCT = TERMINATED`
- `AUTONOMOUS_ATTRIBUTION_MVP = DO_NOT_BUILD`

## Current evaluation

- Status: `BLOCKED`
- Certification: `INCONCLUSIVE`
- Requested cases: `25`
- Executed cases: `0`
- Blocked cases: `25`
- Blockers: `PLATFORM_UNAVAILABLE, HISTORICAL_BUILD_UNREPRODUCIBLE`
- Dependency audit: `PASS`.

## Quality gates

- Commit: `9ddea87f41e4def9d495d894e151225006d205cc`
- Working tree at evidence capture: `CLEAN`
- Tests: `PASS` (83 collected)
- Coverage: `90.34%`
- Ruff / mypy / Bandit: `PASS / PASS / PASS`
- Dependency audit: `PASS`
- Wheel build: `PASS`
- Source distribution build: `PASS`
- Snapshot and leakage checks: `PASS` (12 cases)
- Decisive suite validation: `PASS`

The clean-install smoke test was separately verified from the built wheel with `radar-bench --version` reporting `1.0.0`.

The canonical reference is preserved separately and explicitly marked as not runtime evidence.
