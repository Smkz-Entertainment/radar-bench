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
    radar-bench artifacts verify --suite decisive-v1.1 --artifact-root <artifact-root>

fetch may use the network. verify is local-only. Both commands fail closed on
missing files, unexpected hosts, redirects, size changes, digest changes,
unsafe archives, or extra files.

## Run

    radar-bench validate --suite decisive-v1.2
    radar-bench evaluate --suite decisive-v1.2 --candidate-command docker run --network none --read-only --cap-drop ALL --memory 512m --cpus 1 --pids-limit 128 <image> <argv>

The external candidate command must prove network denial in its Docker argv.
The evaluator creates cryptographically random episode IDs and passes only the
candidate evidence bundle. It never mounts the repository, labels, reference,
credentials, or evaluator mapping.

The immutable v1.1 historical reference remains available for archival checks:

    radar-bench evaluate --suite decisive-v1.1 --artifact-root <artifact-root> --output result.json
    radar-bench verify-results result.json

The evaluate command requires a Linux/x86-64 Docker server. The candidate
execution phase has no network and cannot see evaluator gold. COMPLETED with
certification UNSAFE is the expected scientific result; BLOCKED is an honest
result when Docker, artifacts, or a historical runtime is unavailable.

## Resources and cleanup

Expect about 277 MB of external downloads plus multiple gigabytes of temporary
Docker storage and build layers. A practical minimum is 8 GB RAM, 4 CPU cores,
10 GB free Docker storage, and about 10 minutes for a cold run. Linux/x86-64
is required; Docker Desktop is acceptable only when its Linux engine reports
that architecture.
Do not run historical code on a host containing secrets or a Docker socket
mounted into the case. Remove the externally acquired artifact directory and
unused Docker images only after retaining any evidence required for the
reproduction record. Never disable network denial to repair a case. If the
run is `BLOCKED`, preserve that state and inspect the reported rejection reason
instead of treating it as a score.

For cleanup, remove the external artifact root after exporting the result and
verification record, then remove only Radar Bench-created containers/images.
Do not run historical code with host secrets mounted and do not expose the
Docker socket to a case.
