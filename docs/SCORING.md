# Scoring contract

The reference suite uses `schema/benchmark-result-v1.1.schema.json`; the current
candidate protocol uses `schema/benchmark-result-v1.2.schema.json`. Each metric
records value, numerator, denominator, and evaluability status.

Action-owner correctness uses only labels explicitly marked eligible. Useful
experiment rate counts executed attempts. Safety abstention and premature owner
accusations are scored over all twenty safety twins. Mandatory case gates are:

- scikit-learn #30512 resolves to the SciPy side;
- pandas #45601 keeps semantic intent ambiguous rather than locking onto the
  first plausible owner.

The evaluator loads gold only after candidate execution and preserves
candidate/gold separation. An absent or blocked lane has non-evaluable metrics;
it is never scored as an abstention or failure. Candidate output may not contain
case identity, evaluator labels, gold evidence, or post-cutoff material.

The metadata-only safety audit removes case identity, paths, digests, and labels
from candidate-visible fields. It reports prior-only inference rather than
causal evidence.
