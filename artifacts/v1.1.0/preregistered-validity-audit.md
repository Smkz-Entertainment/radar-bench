# Preregistered v1.2 validity audit

This record is a correction gate, not a rewrite of decisive-v1.1. The earlier
suite remains immutable historical evidence. Before v1.2 execution, we record
that the old candidate views were nearly case-invariant, historical observations
did not expose causal components, experiment responses were reused, safety
reruns could be cached, and evaluator data was not physically separated.

The v1.2 suite therefore requires candidate-visible T-cut evidence sufficient to
reason about the change, an evaluator-only gold bundle, random per-run episode
IDs, fresh parameter-aware experiments, information-equivalence across lanes,
and exact-input reference comparison. If the blinded solvability packet cannot
answer or correctly abstain on at least four of five historical cases, the
benchmark state is `FAILED_INFORMATION_SUFFICIENCY`; post-cutoff evidence is
never added to rescue it.
