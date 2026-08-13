# Releasing

Radar uses immutable source commits, annotated version tags, tag-bound
verification, and manually inspected GitHub Release assets. The preferred
ordinary merge method is squash merging; an audited release commit may use a
maintainer emergency fast-forward when exact-SHA provenance is required.

## Release inputs

For a patch release, update package metadata, documentation, citation metadata,
the evaluator asset, and release tooling without changing benchmark semantics.
The candidate wheel and sdist must not be committed. The evaluator asset is a
separate host/evaluator release asset and is not included in either package.

## Verification sequence

1. Run the full CI matrix and require all five checks: Python 3.11, 3.12, and
   3.13 quality jobs, strict contract/package smoke, and security scans.
2. Build wheel, sdist, and `radar-bench-decisive-v1.2-evaluator.json` from the
   exact source tree.
3. Write `SOURCE-PROVENANCE.json` containing the release tag, package version,
   source commit, source tree, suite, protocol, and all three distributable
   artifacts.
4. Write and verify `SHA256SUMS` for the wheel, sdist, evaluator asset, and
   `SOURCE-PROVENANCE.json`. The checksum manifest is written last and excludes
   itself to avoid circularity. Generate artifact attestations for the wheel,
   sdist, and evaluator.
5. Run `python scripts/audit_release_assets.py <dist>` and inspect package
   contents for evaluator/reference/gold leakage.
6. Create the annotated tag only after the exact source commit is approved.
   The tag must point to that commit and must never be moved.
7. Run `.github/workflows/release.yml` with the existing tag as input.
8. Create the GitHub Release as a draft, download its assets, compare bytes and
   digests to the staged assets, then publish.

The release workflow verifies an existing tag; it never creates or moves a tag.
Do not rewrite `v1.0.0`, `v1.0.1`, or `v1.1.0`.

## Rollback

If a tag-bound check or asset inspection fails, stop publication. Do not retag or
overwrite a release. Correct the source on a new patch branch, rerun the full
verification sequence, and use a new version.
