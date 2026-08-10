# Scoring contract

Results use schema/benchmark-result-v1.1.schema.json and record every metric
as value, numerator, denominator, and evaluability status.

Action-owner correctness uses only labels explicitly marked eligible. Useful
experiment rate counts executed attempts. Safety abstention and premature
owner accusations are scored over all twenty safety twins. The mandatory
case-level gates are:

- scikit-learn #30512 resolves to the SciPy side;
- pandas #45601 keeps semantic intent ambiguous rather than locking onto the
  first plausible owner.

The strict evaluator loads gold only after candidate execution and preserves
candidate/gold separation in the result. An absent or blocked lane has
non-evaluable metrics; it is never scored as an abstention or a failure.
