# Changelog

## 1.1.1 - 2026-08-13

Radar Bench is an evidence-first executable benchmark for testing whether an
investigator can diagnose downstream dependency and version regressions without
falsely blaming an upstream project. The validated research result remains a
small-N negative product conclusion: the executable causal-safety and
historical-attribution checks are validated only at small N, while the
agentic-attribution product was not validated and is not being built.

The current package suite is `decisive-v1.2`, with the preserved historical
`decisive-v1.1` reference available for regression reproduction. Install the
wheel, download the separately released evaluator asset, verify `SHA256SUMS`
and `SOURCE-PROVENANCE.json`, reconstruct and verify the external artifacts,
then follow [the complete quickstart](docs/QUICKSTART.md). The evaluator bundle
is host-only and is never placed in the candidate wheel or container.

The v1.1.1 assets are built from one immutable source commit. The wheel, sdist,
and evaluator asset each receive GitHub artifact attestations; their exact
digests are published in `SHA256SUMS`, and source identity is recorded in
`SOURCE-PROVENANCE.json`. The public gold and non-hidden-test status are
intentional limitations, not claims of private-evaluation security.

Use the private [GitHub Security Advisory route](https://github.com/Smkz-Entertainment/radar-bench/security/advisories/new)
for sensitive vulnerabilities. Cite the release with [CITATION.cff](CITATION.cff)
and read [the limitations](docs/LIMITATIONS.md) before comparing results.

This patch changes repository, packaging, documentation, and GitHub release
engineering only. The decisive-v1.1 and decisive-v1.2 cases, labels, evidence
contract, scoring, frozen baselines, and runtime isolation semantics are
unchanged.

### Added

- a complete release-wheel v1.2 quickstart with artifact and evaluator-bundle
  digest verification;
- the separately distributable `radar-bench-decisive-v1.2-evaluator.json` asset;
- indexed public evidence under `evidence/`;
- stale-current-state and local-link checks;
- package URLs, release provenance, artifact attestations, and repository ruleset
  documentation.

### Changed

- public documentation now describes the released v1.1 line and the current
  package suite accurately;
- generated release binaries and redundant raw scanner receipts are no longer
  tracked in the default branch;
- development dependencies use a transitive, hash-pinned lock;
- community templates, security reporting, and contribution gates reflect the
  public repository.

## 1.1.0 - 2026-08-13

The public release that introduced the separate `decisive-v1.2` suite identity,
candidate/evaluator bundle separation, random per-run episode IDs, a fail-closed
external JSONL candidate protocol, corrected result contracts, and
content-addressed package-resource materialization. Tag `v1.1.0` and its assets
remain immutable.

## 1.0.1 - 2026-08-10

- corrected the immutable `decisive-v1.1` suite identity and strict result schema;
- added self-contained package resources and clean-install workflows;
- added bounded subprocess capture, deterministic Docker cleanup, and secure
  preparation-volume output handling;
- preserved the negative attribution conclusion and A03 correction.

## 1.0.0 - 2026-08-09

The immutable research tag preserving the original v1.0 benchmark evidence.
