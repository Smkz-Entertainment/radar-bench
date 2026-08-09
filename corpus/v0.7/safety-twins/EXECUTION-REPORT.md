# Executable safety-twin run

Date: 2026-08-09

Runtime manifest digest: `sha256:2419caee37e869342921988edc5721807cf35f2da8505b4fe2fbc7bcfb513767`

The manifest validated with zero errors and the unchanged hermetic executor
ran all 20 cases in digest-pinned, network-denied containers. The frozen
investigator was run with the v0.5 episode namespace adapter shown in the
README; no investigator source or heuristic was changed.

| observation from first experiment | cases |
| --- | ---: |
| `BASELINE_NOT_STABLE` | 10 |
| `CANDIDATE_SPECIFIC` | 10 |

| investigator terminal | cases |
| --- | ---: |
| `BOUNDED_INCONCLUSIVE` | 20 |
| `CAUSALLY_ATTRIBUTED` | 0 |

The lane therefore records 20/20 safe abstentions and zero premature owner
accusations for this constructed batch. It does not establish causal-safety
generalization, because the labels are counterfactual evaluator data and no
independent review or holdout run has been performed. It also does not promote
the lane into `corpus/v0.7/executable-subset.json` or change product status.
