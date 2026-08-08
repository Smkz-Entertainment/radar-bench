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
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md), and
[docs/DATA_GOVERNANCE.md](docs/DATA_GOVERNANCE.md).

## Seed corpus status

All 12 manifest rows have local, schema-valid, status-marked curation records.
They are exploratory and reference public URLs rather than redistributing
large third-party content. The worked OpenBLAS example is the complete local
reference record. Headline benchmark claims require independent collection,
temporal review, and a larger holdout.

## License

Code is Apache-2.0. Third-party repositories and linked evidence retain their
own terms.

