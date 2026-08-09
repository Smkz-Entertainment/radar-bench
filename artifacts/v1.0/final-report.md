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
- Blockers: `ARTIFACT_UNAVAILABLE`
- Dependency audit: `PASS`.

## Quality gates

- Commit: `e8701d3fd2b99dbdc76fba5a210ee6c676cd66d3`
- Working tree at evidence capture: `CLEAN`
- Tests: `PASS` (88 collected)
- Coverage: `90.16%`
- Ruff / mypy / Bandit: `PASS / PASS / PASS`
- Dependency audit: `PASS`
- Wheel build: `PASS`
- Source distribution build: `PASS`
- Snapshot and leakage checks: `PASS` (12 cases)
- Decisive suite validation: `PASS`

The clean-install smoke test was separately verified from the built wheel with `radar-bench --version` reporting `1.0.0`.

The canonical reference is preserved separately and explicitly marked as not runtime evidence.
