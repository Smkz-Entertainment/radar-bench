# Radar Attribution Benchmark Protocol v0.1 / v0.2 validation addendum

The benchmark evaluates attribution from public evidence without later
resolution history. It is not a repair benchmark. Correct outcomes include an
upstream regression, expected downstream adaptation, resolver/build/artifact
failure, external-service/CI failure, flaky/mixed evidence, or inconclusive.

## Tracks and temporal integrity

Track A receives initial issue/CI evidence, exact control/candidate identifiers,
environment/dependency metadata, structured failures, relevant source, and
pre-cutoff release notes. It cannot run experiments. Track B receives the same
frozen input and a bounded, non-destructive experiment budget, while future
public history remains hidden.

Each case defines T0 (first signal), Tcut (last visible evidence), and Tgold
(later curator evidence). Evidence after Tcut, mutable content updated after
Tcut, post-cutoff references, fix SHAs, and resolution phrases are excluded.
Retrieval time is not availability time. Unknown timestamps abstain.

## Corpus and labels

Tier A requires a control/candidate or adjacent-version comparison, first-bad
localization where feasible, causal or maintainer evidence, a linked
resolution/workaround/fix, and consistent post-resolution evidence. Tier B is
strong development evidence missing one major item. Tier C is unresolved,
mixed, noisy, or abstention material. Cases from one causal incident stay in a
single split.

The seed set is exploratory. A credible later benchmark should contain 80-120
cases with temporal development/validation/hidden-test splits and no repository
family over 20% of the test split.

## Metrics and gates

Track candidate-induced precision, recall/coverage, high-confidence layer
precision, false upstream accusations, abstention recall on negatives, owner
top-1/top-3, first-bad localization, clean reproducer success, citation
validity, invalid rate, and efficiency. Denominators are always reported;
zero denominators are not silently treated as perfect.

Future product gates are candidate precision >=.95, high-confidence layer
precision >=.95, false upstream accusations <.01, negative abstention >=.95,
first-bad >=.90 where artifacts exist, clean reproducer >=.95, known-cause
retrieval >=.95, and temporally valid citations = 1.00. Seed results do not
establish these production claims.

## v0.2 admission and safety gates

The v0.2 corpus target is 100 cases with this deliberate distribution: 25 true
upstream regressions, 15 downstream incompatibilities, 15 dependency or
transitive failures, 10 resolution/artifact failures, 10 CI/infrastructure
failures, 10 flaky or nondeterministic cases, 5 expected breaking changes, and
10 ambiguous cases. The repository contains the plan only; it currently has
zero admitted gold cases.

Gold labels must be derived from later public evidence independent of the
evaluated agent. Admission requires temporal metadata, causal evidence, and a
resolution or post-fix signal. Cases without that evidence remain outside the
gold set.

The v0.2 verdict set adds `confounded_change`. It means the candidate/control
difference is observed, but multiple relevant variables changed and causal
ownership cannot safely be assigned. It is an abstention outcome.

Numeric confidence is accompanied by evidence classes: `OBSERVED`,
`REPRODUCED`, `CAUSALLY_SUPPORTED`, and `CONFIRMED`. Calibration is reported
with reliability bins, expected calibration error, and Brier score. The first
evaluation set requires zero false high-confidence upstream accusations.

## v0.3 Gold Corpus & Blind Attribution

v0.3 keeps the v0.2 plan frozen and introduces two separate corpora: 120
attribution cases and 300 safety/abstention cases, including at least 50
counterfactual variants. Planned records, counterfactual source links, and
exploratory development metrics are never treated as labels.

High-confidence admission is fail-closed. It requires independent post-cutoff
public evidence covering maintainer/upstream confirmation, first bad,
causal intervention, minimized reproduction, linked fix/revert, and post-fix
recovery, plus immutable candidate/gold snapshots and independent review.

The v0.3 candidate boundary is physical and capability-scoped: candidate
input is cutoff-only, gold is scorer-only, candidate network access is denied,
and the scorer runs after the candidate output is frozen. Candidate induction,
causal component, action owner, and first bad are scored independently. Exact
one-sided binomial bounds are required for safety claims; an empty or small
sample is not a zero-failure pass.

## Provider ablation

Run deterministic, deterministic plus local/open model, and deterministic plus
Codex lanes when predictions exist. Codex qualifies only with a measured
owner-accuracy, experiment-efficiency, or resolved-case gain and no more than
0.5 percentage points added false high-confidence blame. Better prose is not a
qualifying result.
