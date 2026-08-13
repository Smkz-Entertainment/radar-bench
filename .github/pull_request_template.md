## Summary

<!-- What changed and why? -->

## Evidence

- [ ] `python -m pytest -q`
- [ ] line coverage is at least 90% and branch coverage is at least 80%
- [ ] `python -m ruff check .`
- [ ] `python -m mypy --strict src`
- [ ] `python -m bandit -q -r src scripts`
- [ ] `python -m pip_audit .`
- [ ] `python -m radar_bench.cli validate --suite decisive-v1.1`
- [ ] `python -m radar_bench.cli validate --suite decisive-v1.2`
- [ ] package audit passed for wheel, sdist, and evaluator asset
- [ ] candidate/gold separation audit passed
- [ ] Docker protocol smoke ran where relevant
- [ ] `python scripts/check_public_state.py`
- [ ] `python scripts/check_links.py`
- [ ] `git diff --check`

## Integrity and safety

- [ ] Frozen v0.4/v0.5 baselines were not tuned or rewritten.
- [ ] No gold, post-cutoff, or evaluator-only data was added to candidate-visible runtime paths.
- [ ] Any executable-case change has exact hashes, network denial, resource limits, and a rejection/blocker record where applicable.
- [ ] No secrets, generated build output, local paths, or temporary artifacts are included.
- [ ] The worktree is clean after validation.

## Release impact

- [ ] This change does not claim production readiness or population-level accuracy.
- [ ] If release metadata changed, `CHANGELOG.md`, `CITATION.cff`, and relevant evidence were updated.
