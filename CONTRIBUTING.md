# Contributing to Radar Bench

Radar Bench is an evidence-first benchmark. Contributions must preserve the distinction between a historical reference result, a live executable observation, and an evaluator-only label.

## Development checks

```text
python -m pytest -q
python -m ruff check .
python -m mypy src
python -m bandit -q -r src
python -m radar_bench.cli validate --suite decisive-v1
git diff --check
```

The canonical executable suite additionally requires Linux/x86-64 Docker and the exact sealed artifacts. Do not report a blocked run as a pass.

## New cases

Start with a candidate inventory entry and a rejection reason if the case cannot be sealed. A promoted case must reconstruct the historical downstream revision, archive every required artifact, run independent control and candidate environments, rerun from fresh containers with networking disabled, and keep post-cutoff gold evidence outside the candidate-visible tree. Use only these rejection reasons: `ARTIFACT_UNAVAILABLE`, `PLATFORM_UNAVAILABLE`, `HISTORICAL_BUILD_UNREPRODUCIBLE`, `DEPENDENCY_NOT_ARCHIVED`, `NONDETERMINISTIC`, and `REQUIRES_UNAVAILABLE_HARDWARE`.

Do not implement special support for an incident to make it score. Seal the actual case or reject it with evidence.

## Frozen research

Do not tune or rewrite the v0.4 static baseline or the frozen v0.5 investigator. Any new evaluator must preserve their hashes and report its own implementation separately. Do not add Codex, paid, or hosted models to the canonical suite.
