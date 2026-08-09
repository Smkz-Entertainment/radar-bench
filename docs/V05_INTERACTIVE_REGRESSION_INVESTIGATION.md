# v0.5 Interactive Regression Investigation

v0.5 is a bounded experiment on the committed v0.4 pilot. It does not expand
the corpus, alter v0.4 labels, or create a product UI.

Each evaluator-owned `InvestigationEpisode` records T0, Tcut, a cutoff-only
candidate snapshot, a scorer-only hidden gold reference, observed facts,
plausible components, the complete experiment action space, historical
evidence, a terminal gold attribution/owner/mitigation record, an
attributability class, and independent provenance. Candidate views are
constructed without the hidden packet or post-Tcut evidence.

The replay oracle is deterministic and network-free. It returns only an
experiment result, permitted execution evidence, and an opaque provenance id.
Unavailable evidence is returned as `UNAVAILABLE`; malformed or logically
invalid requests are recorded as `INVALID`. A real container adapter was not
run because no safe, secret-free reproduction was available for this historical
corpus.

The heuristic lane follows:

`OBSERVE -> HYPOTHESIZE -> SELECT_EXPERIMENT -> EXECUTE_OR_REPLAY -> UPDATE_HYPOTHESES`

It has a maximum of five substantive experiments per episode and never turns
the highest-probability hypothesis into an owner claim without a causal result.
The implementation records every request, result, hypothesis ledger update,
terminal state, and provenance reference.

Run and validate the pilot offline:

```text
$env:PYTHONPATH = "src"
python scripts/run_v05_investigation.py
python -m radar_bench.cli validate-v05-episodes
```

The authoritative v0.4 static result remains `PIVOT_REQUIRED` with
`STATIC_OWNER_ATTRIBUTION = FAILED_VALIDATION`. v0.5 lane B currently clears
its bounded continuation gates, so `AGENTIC_CAUSAL_INVESTIGATION` is
`ACTIVE_VALIDATED`; this is a pilot continuation decision, not production
readiness. Lanes C and D are explicitly `BLOCKED_EXTERNAL` when no suitable
local model or credentials/credits are available.

Required evidence is under `artifacts/release-evidence/`, with the summary in
`artifacts/v05-final-report.md` and the machine-readable result in
`artifacts/v05-result.json`. The pre-existing frozen v0.3
`ablation-results.json` is preserved byte-for-byte; the v0.5 ablation is
versioned as `ablation-results-v05.json` to avoid mutating that artifact.
