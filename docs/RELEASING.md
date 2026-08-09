# Releasing Radar Bench

The repository uses an annotated local tag only after every release gate passes. The GitHub release workflow is tag-driven, verifies the package version, runs the authoritative CI contract, validates `decisive-v1`, runs the canonical evaluator, builds distributions, checks the diff, and creates a draft release. A blocked or inconclusive evaluator result stops the workflow before any draft is created.

## Maintainer checklist

1. Confirm the worktree contains only intentional release files.
2. Run `python scripts/ci.py` and preserve its machine-readable output.
3. Run `radar-bench evaluate --suite decisive-v1` on the supported Linux/x86-64 Docker host.
4. Confirm `artifacts/v1.0/release-gates.json` is `READY_FOR_PUBLIC_RELEASE` and the dependency audit is `PASS`.
5. Update `CHANGELOG.md`, `CITATION.cff`, and the release evidence.
6. Create an annotated `v1.0.0` tag only after the previous checks pass.
7. Push the tag through the normal protected GitHub path; review the generated draft release before publishing.

The workflows use explicit least-privilege permissions, concurrency cancellation for CI, immutable action SHAs, Dependabot updates for action and Python dependencies, and no `pull_request_target` workflow. GitHub’s security guidance recommends full-length commit-SHA pinning for actions: <https://docs.github.com/en/actions/reference/security/secure-use>.

Do not use a reference result, a replay oracle, an unavailable artifact, or a platform mismatch to satisfy a release gate.
