# Deterministic baseline rules

1. Control passes and candidate consistently fails: candidate-induced evidence;
   confidence remains medium until causal evidence is available.
2. Both fail with matching failure: baseline-already-broken or inconclusive;
   never blame upstream.
3. Missing/uninstallable artifacts: packaging or dependency-resolution layer.
4. 404/DNS/TLS/remote fixture failures: external-service/data layer.
5. One-off worker crash, xdist crash, or flaky signal: abstain, recommend
   repeated runs.
6. Explicit deprecation/release evidence can identify expected downstream
   adaptation, but not from model confidence alone.
7. Exact A/B or adjacent revision evidence strengthens first-bad localization.
8. Transitive native changes isolated while direct upstream is unchanged are
   shared-dependency candidates.
9. Mixed fingerprints or contradictory evidence produce multiple-layers or
   unknown with a split/repeat recommendation.

Every prediction records fired rules, unsatisfied alternatives, citations, and
the next highest-information safe experiment.

