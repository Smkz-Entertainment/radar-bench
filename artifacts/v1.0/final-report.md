# Radar Bench 1.0.0 release evidence

Release readiness: **READY_FOR_PUBLIC_RELEASE**

This bundle records the v1 OSS benchmark boundary. It does not convert a blocked runtime into a benchmark score and does not claim product or production validation.

## Scientific decision

- `EXECUTABLE_CAUSAL_SAFETY = VALIDATED_SMALL_N`
- `HISTORICAL_ATTRIBUTION_EXECUTABILITY = VALIDATED_SMALL_N`
- `AGENTIC_CAUSAL_INVESTIGATION = FAILED_VALIDATION`
- `CROSS_REPOSITORY_ATTRIBUTION_PRODUCT = TERMINATED`
- `AUTONOMOUS_ATTRIBUTION_MVP = DO_NOT_BUILD`

## Current evaluation

- Status: `COMPLETED`
- Certification: `UNSAFE`
- Requested cases: `25`
- Executed cases: `25`
- Blocked cases: `0`
- Blockers: `none`
- Dependency audit: `PASS`.
- Public artifact catalog: `PASS` (5 bundles; external verification: `READY`).

## Quality gates

- Commit: `a7fbbcaa4669d97e872cec58d46d432912336e23`
- Working tree at evidence capture: `CLEAN`
- Tests: `PASS` (121 collected)
- Coverage: `90.24%`
- Ruff / mypy / Bandit: `PASS / PASS / PASS`
- Dependency audit: `PASS`
- Wheel build: `PASS`
- Source distribution build: `PASS`
- Snapshot and leakage checks: `PASS` (12 cases)
- Decisive suite validation: `PASS`

The clean-install smoke test was separately verified from the built wheel with `radar-bench --version` reporting `1.0.0`.

The canonical reference is preserved separately and explicitly marked as not runtime evidence.
