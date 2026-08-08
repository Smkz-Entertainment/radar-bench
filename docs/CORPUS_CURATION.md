# Corpus curation

Curators record T0, Tcut, Tgold, source URLs, digests, temporal decisions,
duplicate clusters, and uncertainty. Tier A needs causal comparison plus
resolution-grade evidence; Tier B is development-only; Tier C is unresolved or
challenge/abstention material. Do not force an owner label.

The manifest is a resumable queue. A network-blocked item is marked blocked,
not collected. Add a case by linking public sources, preserving only minimal
content, writing a full RegressionCase, building input/gold snapshots, and
running validation and leakage checks.

## v0.2 independent admission

`corpus/v0.2` is an admission plan, not a benchmark result. A record begins as
`planned` and cannot carry a gold label. It may become `admitted` only when the
later public record independently establishes both causal support and a
resolution or post-fix outcome, with timestamps after the case cutoff and an
independent review status. The evaluated deterministic, local-model, or Codex
lane cannot be the source of the gold label.

Negative controls are first-class cases. Dead URLs, outages, missing wheels,
resolver drift, worker crashes, flakiness, baseline failures, and other
confounders should remain abstention material unless later evidence establishes
another outcome. A confounded case uses `candidate_induced: null` and the
v0.2 `confounded_change` verdict rather than forcing ownership.

## v0.3 curation boundary

The v0.3 plan is split into `corpus/v0.3/attribution-gold` and
`corpus/v0.3/safety-abstention`. It contains 120 attribution slots, 300 safety
slots, and 50 explicitly marked counterfactual variants. These records are
planned inventory only.

An admitted v0.3 record must carry exact public URLs, post-cutoff immutable
source snapshots, the complete causal/reproduction/fix/recovery evidence
combination, physically separate candidate and gold packet digests, and
independent review. A counterfactual cannot inherit its source positive label;
it needs its own evidence packet to be admitted. If any requirement is absent,
the record stays non-admitted and the scorer excludes it.
