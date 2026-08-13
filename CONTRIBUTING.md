# Contributing

Radar Bench is an evidence-first benchmark. Preserve the separation between
candidate-visible runtime data, evaluator-only labels, historical evidence, and
reference results. Do not tune a result after observing it.

Before opening a pull request, run the supported Python versions or the
repository CI equivalent:

    python -m pytest -q
    python -m coverage erase
    python -m coverage run --branch -m pytest -q
    python -m coverage json -o coverage.json
    python scripts/check_coverage.py coverage.json
    python -m ruff check .
    python -m mypy --strict src
    python -m bandit -q -r src scripts
    python -m pip_audit .
    cffconvert --validate -i CITATION.cff
    python scripts/check_public_state.py
    python scripts/check_links.py
    git diff --check

Changes to executable cases require a new immutable suite identity, exact
artifact hashes, network denial, resource limits, and a rejection or blocker
record where applicable. Do not add secrets, private paths, generated caches,
downloaded wheel bytes, evaluator gold, or post-cutoff evidence to candidate-
visible runtime directories.

The v1.2 evaluator bundle is host/evaluator-only. It may be supplied explicitly
to validation and release tooling, but it must never be packaged into the
candidate wheel or mounted into the candidate container.

Supported historical blockers remain explicit: `ARTIFACT_UNAVAILABLE`,
`PLATFORM_UNAVAILABLE`, `HISTORICAL_BUILD_UNREPRODUCIBLE`,
`DEPENDENCY_NOT_ARCHIVED`, `NONDETERMINISTIC`, and
`REQUIRES_UNAVAILABLE_HARDWARE`.

## Pull request gates

Every change should report tests, separate line coverage of at least 90% and
branch coverage of at least 80%, Ruff, strict mypy, Bandit, pip-audit,
decisive-v1.1 validation, decisive-v1.2 validation, package audit,
candidate/gold separation, protocol smoke where relevant, stale-state scan,
and worktree cleanliness. The preferred merge method is squash merging for
ordinary maintenance; audited release commits may use the documented emergency
exact-SHA procedure.
