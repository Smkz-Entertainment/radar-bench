# v0.7 Executable Investigation Benchmark

This directory is the preparation boundary for the v0.7 micro-corpus. It is
intentionally unsealed: the checked-in manifest contains zero cases and is not
an evaluation result.

A future sealed case must include exact control/candidate workspaces, digest-
pinned local artifacts, Linux/x86-64 container identity, deterministic commands,
and recipes for the complete common capability surface. Evaluations run with
network denied, gold and historical discussion unmounted, and local artifacts
only.

The current state is `PRODUCT_VALIDATION = BLOCKED_BY_EXECUTABILITY`. The v0.4
OSINT records and v0.5 replay episodes are retained for development and
qualitative work, but they cannot populate this executable manifest or certify
the Radar hypothesis.
