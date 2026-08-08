# Radar Bench v0.3 implementation plan

The v0.1 foundation and v0.2 attribution-validation contracts are frozen.
Changes in this milestone are additive and versioned.

## Delivered engineering

- Separate 120-case attribution and 300-case safety/abstention plans, with 50
  counterfactual variants and balanced D1-D5 attribution difficulty.
- Fail-closed `GoldAdmission` requiring independent post-cutoff evidence,
  immutable snapshots, and independent review.
- Causal ontology fields and separate scoring for induction, causal component,
  action owner, and first bad.
- Candidate-only temporal boundary with denied network policy and a separate
  scorer manifest.
- Exact one-sided binomial safety bounds, calibration metadata, stage/freeze
  hashes, and blocked external ablation lane records.

## Still required before validation

- Read-only OSINT collection and independent review of every admitted record.
- Physically materialized candidate/gold snapshots with immutable CAS digests.
- Freeze implementation and corpus hashes before hidden scoring.
- Score at least 300 independently admitted safety cases and the full
  attribution set; publish exact counts and confidence bounds.
- Run available deterministic/model lanes under the same Tcut/network policy.

No planned record is a pass, and no result from this milestone is
production-ready until the hard gates are demonstrated.
