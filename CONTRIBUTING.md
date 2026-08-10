# Contributing

Radar Bench is an evidence-first benchmark. Preserve the separation between
candidate-visible runtime data, evaluator-only labels, historical evidence,
and reference results.

Before opening a change:

    python -m pytest -q
    python -m ruff check .
    python -m mypy --strict src
    python -m bandit -q -r src scripts
    radar-bench validate --suite decisive-v1.1
    git diff --check

Do not tune or rewrite the frozen v0.4/v0.5 baselines. A new historical case
must be sealed and replayed as-is or rejected with evidence using one of the
documented reasons: ARTIFACT_UNAVAILABLE, PLATFORM_UNAVAILABLE,
HISTORICAL_BUILD_UNREPRODUCIBLE, DEPENDENCY_NOT_ARCHIVED, NONDETERMINISTIC,
or REQUIRES_UNAVAILABLE_HARDWARE.

Do not add secrets, private paths, generated caches, downloaded wheel bytes,
or evaluator gold to candidate-visible runtime directories. Changes to the
suite identity require a correction record and a new immutable suite version.

The configured 90% coverage threshold reports the small core module set in
`pyproject.toml`; it is not a claim that every Docker/provider integration
branch is covered by that aggregate. Those integration paths must still be
covered by their focused contract, bounded-process, package-smoke, and
fail-closed tests.
