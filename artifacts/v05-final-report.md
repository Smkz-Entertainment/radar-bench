# Radar Bench v0.5 Interactive Regression Investigation

This is a bounded replay-first experiment on the committed v0.4 corpus. The v0.4 corpus, labels, and authoritative result are unchanged.

## Status

- `STATIC_OWNER_ATTRIBUTION`: `FAILED_VALIDATION`; frozen v0.4 decision remains `PIVOT_REQUIRED`.
- `AGENTIC_CAUSAL_INVESTIGATION`: `ACTIVE_VALIDATED`.
- Episodes: `60`; substantive experiments: `80`.
- Immutable corpus digest: `sha256:ffbce9c1ece8a8afbcd6c7342a4224383d8b80a5c6e7e06e1e17401799e28621`.
- Implementation digest: `sha256:11098270d0f4ab26277ad2b63208dccf20b0c3300d9a1c54838092b0f9759297`.

## Lane B results

- Candidate-induced precision: `1.0`.
- Action-owner precision on attributable claims: `1.0`.
- Correct resolution or abstention: `1.0`.
- Useful experiment rate: `0.9`.
- Median experiments per resolution: `1.0`.
- Safety abstention recall: `1.0`.

## Gates

- `candidate_induced_precision`: `pass` (value `1.0`, threshold `0.85`).
- `action_owner_precision`: `pass` (value `1.0`, threshold `0.8`).
- `correct_resolution_or_abstention`: `pass` (value `1.0`, threshold `0.8`).
- `safety_abstention_recall`: `pass` (value `1.0`, threshold `0.95`).
- `false_premature_or_high_confidence_owner`: `pass` (value `0`, threshold `0`).
- `valid_requests`: `pass` (value `1.0`, threshold `0.9`).
- `useful_experiments`: `pass` (value `0.9`, threshold `0.6`).
- `median_experiments`: `pass` (value `1.0`, threshold `3`).

The experiment interface is replay-only for this pilot because the corpus is historical and no safe, secret-free container reproduction was available. No candidate lane receives future comments, gold owners, or resolution text. The next action for an unresolved case is another permitted experiment or abstention; it is never a highest-probability owner guess.
