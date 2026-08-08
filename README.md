# Ecosystem Radar / Radar Bench

Radar Bench v0.1 is an evidence-first, read-only benchmark foundation for
asking whether a downstream failure is caused by an upstream change. It stores
public evidence by digest, reconstructs a T0/Tcut/Tgold boundary, normalizes
failures deterministically, and evaluates conservative predictions.

This is not an autonomous maintainer-blaming system. A green check does not
prove universal compatibility, and an unsupported owner claim is a failure.
Correct abstention is a successful result.

## Scope

The release contains canonical RegressionCase, Prediction, and ExperimentPlan
schemas; semantic validation; a read-only GitHub collector; CAS/SQLite storage;
temporal snapshots and leakage scanning; pytest/JUnit/GitHub failure
normalization; deterministic baseline rules; scoring/gates; safe provider
interfaces; and a 12-row public seed manifest with status-marked local records.

The v0.2 validation milestone is separate from that frozen foundation. It adds
a 100-slot adversarial admission plan, independent-gold admission rules,
confounded-change abstention, calibration metrics, and exact provider-lane
ablation accounting. The plan contains zero admitted gold cases until later
public evidence satisfies the admission protocol.

The v0.3 research milestone is additive and separate again. It plans distinct
120-case attribution and 300-case safety/abstention corpora, including 50
counterfactual variants, and adds fail-closed high-confidence admission,
versioned causal ontology, temporal-blind candidate execution, field-level
metrics, and exact small-sample safety bounds. The checked-in v0.3 records are
plans with zero admitted labels; they are not benchmark results.

There is no dashboard, GitHub write integration, notification system,
arbitrary-repository executor, hosted service, billing, repair generator, or
credential-requiring model integration.

## Installation and quick start

```text
python -m venv .venv
python -m pip install .
radar-bench doctor
radar-bench validate-corpus
python scripts/ci.py
```

The default checks are network-free. Collection is opt-in and read-only:

```text
radar-bench collect --issue https://github.com/owner/repo/issues/1 --cutoff 2024-01-01T00:00:00Z --output .radar-cache
```

## Safety and evidence

Only evidence explicitly attested as available by Tcut enters an inference
packet. Gold resolution material is kept separately. Provider output is strict
JSON data, not instructions, and cannot upgrade confidence by asserting its own
certainty. Public-source collection can be blocked by network/rate limits; the
queue records that state instead of claiming completion.

See [docs/BENCHMARK_PROTOCOL.md](docs/BENCHMARK_PROTOCOL.md),
[docs/V03_GOLD_CORPUS_AND_BLIND_ATTRIBUTION.md](docs/V03_GOLD_CORPUS_AND_BLIND_ATTRIBUTION.md),
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md), and
[docs/DATA_GOVERNANCE.md](docs/DATA_GOVERNANCE.md).

Validate the v0.2 plan without treating planned records as gold:

```text
radar-bench validate-v02-corpus
radar-bench baseline corpus/snapshots/RADAR-OSINT-008 --v02
radar-bench validate-v03-corpus --json
radar-bench baseline corpus/snapshots/RADAR-OSINT-008 --v03
```

## Seed corpus status

All 12 manifest rows have local, schema-valid, status-marked curation records.
They are exploratory and reference public URLs rather than redistributing
large third-party content. The worked OpenBLAS example is the complete local
reference record. Headline benchmark claims require independent collection,
temporal review, and a larger holdout.

## License

Code is Apache-2.0. Third-party repositories and linked evidence retain their
own terms.
