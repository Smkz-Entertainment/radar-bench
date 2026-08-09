# Releasing Radar Bench

The repository uses an annotated local tag only after every release gate passes. The GitHub release workflow is tag-driven, verifies the package version, runs the authoritative CI contract, validates `decisive-v1`, runs the canonical evaluator, builds distributions, checks the diff, and creates a draft release. A blocked or inconclusive evaluator result stops the workflow before any draft is created.

## Maintainer checklist

1. Confirm the worktree contains only intentional release files.
2. Run `python scripts/ci.py` and preserve its machine-readable output.
3. Reconstruct and verify the five `RECONSTRUCT_ONLY` bundles with `radar-bench artifacts fetch --suite decisive-v1` and `radar-bench artifacts verify --suite decisive-v1 --artifact-root <artifact-root>`.
4. Run `radar-bench evaluate --suite decisive-v1 --artifact-root <artifact-root>` with a supported Linux/x86-64 Docker engine. Docker Desktop's Linux engine is acceptable. The expected scientific result is `COMPLETED` with certification `UNSAFE`, because the benchmark reproduces the failed attribution thesis.
5. Run `python scripts/build_v1_evidence.py --artifact-root <artifact-root>` and confirm `artifacts/v1.0/release-gates.json` is `READY_FOR_PUBLIC_RELEASE` and the dependency audit is `PASS`.
6. Update `CHANGELOG.md`, `CITATION.cff`, and the release evidence.
7. Create an annotated `v1.0.0` tag only after the previous checks pass.
8. Push the tag through the normal protected GitHub path; review the generated draft release before publishing.

The workflows use explicit least-privilege permissions, concurrency cancellation for CI, immutable action SHAs, Dependabot updates for action and Python dependencies, and no `pull_request_target` workflow. GitHub’s security guidance recommends full-length commit-SHA pinning for actions: <https://docs.github.com/en/actions/reference/security/secure-use>.

Do not use a reference result, a replay oracle, an unavailable artifact, or a platform mismatch to satisfy a release gate.
