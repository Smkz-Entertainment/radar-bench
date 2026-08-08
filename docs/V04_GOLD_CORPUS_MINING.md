# v0.4 Gold Corpus Mining and Admission

v0.4 is the first real-public-OSINT corpus pilot. It is additive to the frozen
v0.3 apparatus and does not turn corpus validation into a capability or
production-readiness claim.

## Pilot contract

The pilot target is 20 admitted attribution records and 40 admitted safety
records. The implementation intentionally mines a small 25-row attribution
candidate table and a 40-row safety table so unresolved cases remain visible
instead of being silently relabeled.

Every record carries a `t0`, a source cutoff, a content-addressed source
snapshot, a resolution chain, a cutoff-only candidate snapshot, and a
scorer-only post-cutoff gold packet. The candidate packet never contains gold
labels. A source that is unavailable, temporally unverified, duplicated, or
insufficiently resolved is blocked or rejected with an explicit reason.

Gold-A requires upstream confirmation, first-bad evidence, a causal
intervention, a reproducer, a resolution, and post-fix recovery. Gold-B is an
outcome-level attribution record and is excluded from strict action-owner
scoring. Safety-A records are negative controls whose expected behavior is
abstention.

The rejection taxonomy is defined in `radar_bench.corpus.v04`:

- `NO_INDEPENDENT_CONFIRMATION`
- `NO_TEMPORAL_BOUNDARY`
- `MISSING_CONTROL`
- `AMBIGUOUS_OWNER`
- `BROKEN_EXTERNAL_ARTIFACT`
- `SOURCE_UNAVAILABLE`
- `DUPLICATE_INCIDENT`
- `INSUFFICIENT_RESOLUTION_EVIDENCE`

## Early continuation gates

After the pilot, mining continues only if all four deterministic checks pass:

- action-owner precision at least 0.70;
- candidate-induced precision at least 0.80;
- abstention recall at least 0.90; and
- zero high-confidence false upstream accusations.

These are continuation thresholds, not production gates. Codex and local-model
lanes are deliberately not run during v0.4 corpus admission.

## Commands and evidence

Run the read-only OSINT miner with:

```powershell
$env:PYTHONPATH = "src"
python scripts/mine_v04_pilot.py
python -m radar_bench.cli validate-v04-corpus --json
```

The miner stores raw public responses in the ignored local CAS at
`.radar-cache/v04-pilot`. Committed pilot evidence is under
`corpus/v0.4/pilot` and `artifacts/release-evidence/v04-*`. The authoritative
offline CI command validates the v0.4 records when they are present.

The pilot is successful as a corpus-denominator milestone only when the 20/40
admission counts and all temporal/provenance checks pass. Capability claims
remain gated by the deterministic early thresholds and later hidden evaluation.
