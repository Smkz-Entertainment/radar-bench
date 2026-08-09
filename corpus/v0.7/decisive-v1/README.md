# decisive-v1

`decisive-v1` is the final Radar Bench executable benchmark contract:

- five sealed historical attribution cases;
- twenty opaque constructed safety twins;
- the static v0.4 baseline, deterministic naïve baseline, and unchanged v0.5 investigator;
- network-denied, digest-pinned Linux/x86-64 Docker execution;
- evaluator-only labels physically outside candidate-visible runtime trees.

The five historical wheelhouses are not redistributed in this repository. Their sealed manifests retain the staging paths and hashes from the case-sealing sprint. A clean checkout therefore validates the suite contract but must report historical execution as `ARTIFACT_UNAVAILABLE`. It must never treat `artifacts/v1.0/canonical-results.json` as a live run.

Run structural validation with:

```text
radar-bench validate --suite decisive-v1
```

Run the supported evaluation command with:

```text
radar-bench evaluate --suite decisive-v1 --output artifacts/v1.0/result.json
```

The second command fails closed when the Linux/x86-64 runtime or sealed historical artifacts are unavailable.
