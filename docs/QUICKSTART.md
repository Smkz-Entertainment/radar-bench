# Quickstart

## Install

Use a fresh virtual environment and install the wheel or sdist you intend to
test:

    python -m venv .venv
    python -m pip install .
    radar-bench doctor
    radar-bench list-suites

## Acquire and verify inputs

The five historical wheelhouses are not committed. Acquire them into an
external directory:

    radar-bench artifacts fetch --suite decisive-v1.1 --output-root <artifact-root>
    radar-bench artifacts verify --suite decisive-v1.1 --output-root <artifact-root>

fetch may use the network. verify is local-only. Both commands fail closed on
missing files, unexpected hosts, redirects, size changes, digest changes,
unsafe archives, or extra files.

## Run

    radar-bench validate --suite decisive-v1.1
    radar-bench evaluate --suite decisive-v1.1 --artifact-root <artifact-root> --output result.json
    radar-bench verify-results result.json

The evaluate command requires a Linux/x86-64 Docker server. The candidate
execution phase has no network and cannot see evaluator gold. COMPLETED with
certification UNSAFE is the expected scientific result; BLOCKED is an honest
result when Docker, artifacts, or a historical runtime is unavailable.

## Resources and cleanup

Expect multiple gigabytes of external wheels and temporary Docker storage.
Do not run historical code on a host containing secrets or a Docker socket
mounted into the case. Remove the externally acquired artifact directory and
unused Docker images only after retaining any evidence required for the
reproduction record. Never disable network denial to repair a case.
