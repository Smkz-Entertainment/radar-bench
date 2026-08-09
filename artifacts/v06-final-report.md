# Radar Bench v0.6 Benchmark Integrity Challenge

v0.6 attacks the benchmark channel while keeping the v0.5 investigator and v0.4 corpus frozen. It is not a product implementation phase.

## Decision

- Benchmark integrity: `FAILED_VALIDATION`.
- v0.5 investigator: `FROZEN_UNDER_AUDIT`.
- Product implementation: `BLOCKED`.
- Decision: `STOP_BENCHMARK_AND_FIX_ORACLE`.

## Gate findings

- `action_space_blindness`: `pass` (value `True`, threshold `None`).
- `metadata_only_owner_prediction`: `pass` (value `0.5`, threshold `0.55`).
- `random_planner_resolution`: `pass` (value `0.2`, threshold `0.3`).
- `naive_planner_resolution`: `fail` (value `0.6`, threshold `0.6`).
- `availability_only_planner_resolution`: `pass` (value `0.0`, threshold `0.8`).
- `frozen_radar_resolution_or_abstention`: `pass` (value `1.0`, threshold `0.8`).
- `frozen_radar_owner_precision`: `pass` (value `1.0`, threshold `0.8`).
- `decoy_false_useful_rate`: `fail` (value `0.6`, threshold `0.4`).
- `oracle_unavailable_status_truthfulness`: `fail` (value `40`, threshold `0`).
- `premature_owner_accusations`: `pass` (value `0`, threshold `0.0`).
- `safety_abstention_recall`: `pass` (value `1.0`, threshold `0.95`).
- `real_execution_correctness`: `not_evaluable` (value `None`, threshold `0.8`).
- `replay_execution_agreement`: `not_evaluable` (value `None`, threshold `0.9`).
- `counterfactual_irrelevant_invariance`: `pass` (value `1.0`, threshold `0.95`).
- `counterfactual_causal_sensitivity`: `pass` (value `1.0`, threshold `0.9`).
- `frozen_investigator_digest`: `pass` (value `True`, threshold `None`).

## Findings

- Metadata-only owner prediction is 0.5 against chance 0.5.
- The full result channel exposes supported components on 12 of 60 probes.
- Decoy false-useful rate on attribution cases is 0.6 (overall 0.2).
- Random attribution resolution is 0.2; naive is 0.6.
- Oracle-availability-only attribution resolution is 0.0 using response status only.
- No real execution subset or replay/execution concordance is available from the frozen corpus.

The v0.5 investigator was not tuned or modified. The replay oracle's direct result behavior and decoy behavior are treated as benchmark-integrity findings, not as evidence for product readiness. Real execution was not claimed because the frozen corpus contains no exact environment/command/lockfile/container manifest.
