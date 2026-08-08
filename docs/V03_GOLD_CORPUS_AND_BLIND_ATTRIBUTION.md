# v0.3 Gold Corpus and Blind Attribution

v0.3 is an additive research milestone. v0.1 and v0.2 schemas, snapshots,
evidence, and behavior remain frozen. The v0.3 records live under
`corpus/v0.3` and are not interchangeable with the v0.2 admission plan.

## Two evaluation corpora

The attribution corpus plans 120 cases across true upstream regressions,
expected breaking changes, downstream incompatibilities, transitive failures,
packaging/build failures, resolver failures, and cross-repository/system cases.
It is balanced across D1–D5 difficulty tiers.

The safety/abstention corpus plans 300 negative or confounded cases, including
baseline-broken, infrastructure, flaky, duplicate, artifact-missing,
resolver-confounded, unsafe-to-attribute, and 50 counterfactual variants.
Counterfactuals reference a positive source only as a mutation origin; they do
not inherit its label.

The checked-in records are curation plans with null labels. A planned record is
never a gold case and cannot establish a safety rate.

## GoldAdmission

`validate_gold_admission` admits a high-confidence record only when the record
has independent post-cutoff evidence for maintainer/upstream confirmation,
first-bad version or revision, causal intervention, minimized reproduction,
linked fix or revert, and post-fix downstream recovery. It also requires
public source URLs, immutable evidence digests, separate cutoff-only candidate
and scorer-only gold packet digests, and independent human/OSINT review.

Insufficient evidence remains planned, candidate, rejected, or blocked. A
provider cannot create a gold label.

## Temporal blindness

Candidate inference receives an input packet and a capability-scoped candidate
filesystem. The gold packet is physically separate, is used only for later
digesting/scoring, and is never included in the candidate packet. The repository
client rejects network access when the blind-run policy is `denied`. The local
harness proves that the candidate capability cannot enumerate or read the gold
tree. This is a portable boundary; arbitrary third-party native code still
requires an OS-level sandbox before a hosted security claim.

## Ontology and measurement

v0.3 adds trigger component/change, manifestation project/layer, root-cause
component/mechanism, action-owner repository, first-bad version/revision,
confounders, and evidence class. Candidate induction, causal component, action
owner, and first-bad localization are scored independently. Evidence classes
are `OBSERVED`, `REPRODUCED`, `CANDIDATE_SPECIFIC`, `CONFOUNDED`,
`CAUSALLY_SUPPORTED`, and `CONFIRMED`; confidence is an internal numeric
quantity and is reported with ECE, Brier, reliability bins, and exact counts.

Safety evidence uses an exact one-sided binomial 95% upper bound. Zero observed
failures with fewer than 300 independently admitted safety cases is not a
qualified safety result.

## Current boundary

The v0.3 engineering machinery is implemented and locally checked. The
required public curation, independent admission, hidden freeze/scoring, and
model-lane ablation remain open. The release decision is therefore `PARTIAL`,
never production-ready.
