# v0.7 Executable Investigation Benchmark

v0.7 is the decisive follow-up to the failed v0.6 integrity challenge. It
keeps the v0.5 investigator at commit `60ccc18` and replaces historical replay
certification with actual experiments in sealed, digest-pinned environments.
Historical replay remains useful for development and qualitative research, but
it cannot certify the Radar hypothesis.

## Runtime contract

Every sealed case must provide:

- a Tcut candidate view;
- exact control and candidate workspaces;
- locally cached source, wheels/sdists, lockfiles, and reproducer artifacts;
- Linux/x86-64 and a digest-pinned container image;
- deterministic commands for every capability in the common interface.

The common interface is fixed globally: `rerun`,
`change_dependency_version`, `freeze_dependency`, `bisect_component`,
`toggle_environment_variable`, `run_minimal_test`, and
`inspect_dependency_graph`. Requests outside that interface are rejected before
case lookup. In-interface requests are executed by the hermetic container
executor; they do not consult a historical trajectory or return
`AVAILABLE`/`UNAVAILABLE` clues.

Preparation may use the network. Evaluation requires network denied, gold and
historical discussion unmounted, and local artifacts only. Evaluator gold is
loaded only after runtime execution for scoring.

## Pilot gates

The executable pilot requires action-owner precision >=80%, candidate-induced
precision >=85%, correct resolution or abstention >=80%, safety abstention
recall >=95%, zero premature owner accusations, useful experiment rate >=60%,
median experiments to resolution <=3, naive resolution <60%, at least a
 20-point advantage over naive, and no regression against the no-experiment
 baseline. Random and naive planners are scored against the same executor. The
 frozen-investigator digest must match.

## Current state

`corpus/v0.7/executable-subset.json` is intentionally unsealed with zero cases.
The current result is therefore:

- `PRODUCT_VALIDATION = BLOCKED_BY_EXECUTABILITY`;
- `AGENTIC_CAUSAL_INVESTIGATION = UNVALIDATED`;
- `V05_INVESTIGATOR = FROZEN_UNDER_AUDIT`;
- `REPLAY_ORACLE_CERTIFICATION = REJECTED`.

No historical replay rows or synthetic execution results were promoted to v0.7.
The next valid step is preparation and independent sealing of a small,
high-quality executable micro-corpus, not another replay benchmark or product
implementation.
