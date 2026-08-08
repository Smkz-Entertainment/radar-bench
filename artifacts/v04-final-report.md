# v0.4 Gold Corpus Mining and Admission

## Decision: PIVOT_REQUIRED

The v0.3 apparatus remains frozen. This v0.4 pilot validates the corpus mining, temporal separation, provenance, and deterministic scoring path; it does not establish Radar capability or production readiness.

The pilot admitted 20 attribution records and 40 safety records. 5 records were blocked and 0 were rejected with explicit reasons.

## Early gates

- Abstention recall: 1.00 (pass).
- Candidate-induced precision: 0.60 (fail; threshold 0.80).
- Action-owner precision: 0.00 (fail; threshold 0.70).
- High-confidence false upstream failures: 0 (pass).

The pilot therefore requires a deterministic-baseline pivot before more corpus mining. Local-model and Codex lanes were not run by design.

## Evidence

- `artifacts/release-evidence/v04-pilot-report.json`
- `artifacts/release-evidence/v04-corpus-stats.json`
- `artifacts/release-evidence/v04-early-gates.json`
- `artifacts/release-evidence/v04-error-taxonomy.json`
- `artifacts/release-evidence/v04-rejection-report.json`
