# Radar Attribution Benchmark Protocol v0.1

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

## Provider ablation

Run deterministic, deterministic plus local/open model, and deterministic plus
Codex lanes when predictions exist. Codex qualifies only with a measured
owner-accuracy, experiment-efficiency, or resolved-case gain and no more than
0.5 percentage points added false high-confidence blame. Better prose is not a
qualifying result.

