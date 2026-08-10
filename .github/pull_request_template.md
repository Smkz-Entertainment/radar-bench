## Summary

<!-- What changed and why? -->

## Evidence

- [ ] `python -m pytest -q`
- [ ] `python -m ruff check .`
- [ ] `python -m mypy --strict src`
- [ ] `python -m bandit -q -r src`
- [ ] `python -m radar_bench.cli validate --suite decisive-v1.1`
- [ ] `git diff --check`

## Integrity and safety

- [ ] Frozen v0.4/v0.5 baselines were not tuned or rewritten.
- [ ] No gold, post-cutoff, or evaluator-only data was added to candidate-visible runtime paths.
- [ ] Any executable-case change has exact hashes, network denial, resource limits, and a rejection/blocker record where applicable.
- [ ] No secrets, generated build output, local paths, or temporary artifacts are included.

## Release impact

- [ ] This change does not claim production readiness or population-level accuracy.
- [ ] If release metadata changed, `CHANGELOG.md`, `CITATION.cff`, and relevant evidence were updated.
