# Ecosystem Radar v0.1 implementation plan / v0.2 validation milestone

The release is organized as M0-M9: bootstrap; canonical schemas; read-only
collection/storage; temporal snapshots; normalization; deterministic baseline;
evaluation/gates; provider ablations; seed corpus; and release hardening.

The authoritative local command is `python scripts/ci.py`. A check is only a
pass when it ran to completion and produced concrete evidence. Network-blocked
collection remains queued and is never represented as collected.

## Current checklist

- [x] Bootstrap package, licensing, and repository-owned schemas.
- [x] Dependency-free schema and semantic-validation core.
- [x] CAS/SQLite storage and allowlisted read-only GitHub adapter.
- [x] Temporal input/gold split and leakage scanner.
- [x] Normalization, baseline, metrics, providers, and typed plans.
- [ ] Full external collection and curator verification of all public cases.
- [ ] Release evidence after clean-environment package installation.

## Frozen v0.1 and v0.2 validation work

- [x] Freeze v0.1 schemas and baseline behavior.
- [x] Add independent-gold admission contract with fail-closed semantics.
- [x] Add 100-slot adversarial distribution and negative-control plan.
- [x] Add `confounded_change`, evidence classes, calibration, and abstention
  metrics.
- [x] Add deterministic/local-model/Codex lane comparison and usage accounting
  contract.
- [ ] Collect and independently admit at least 80 cases, targeting 100-120.
- [ ] Clear zero false high-confidence upstream accusations and all v0.2 gates.
