# Quickstart

This is the complete executable `decisive-v1.2` workflow. It uses a published
wheel, the matching public source checkout for candidate-only solvability
evidence, external artifact acquisition, the separately downloadable evaluator
asset, a digest-pinned candidate image, and the strict result verifier. The
wheel intentionally does not contain evaluator material or the candidate-only
solvability receipt.

## 1. Prepare the matching source checkout and release assets

Use a clean checkout of the exact release tag so the candidate-only solvability
receipt and runtime manifests are available without putting them in the wheel.
Choose a disposable working directory and download these four release assets
from the published release you are verifying. The commands below use the
planned `v1.1.1` names; use the matching published tag and filenames when
verifying another release:

    git clone --depth 1 --branch v1.1.1 https://github.com/Smkz-Entertainment/radar-bench.git radar-bench-source
    cd radar-bench-source
    python -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    curl --fail --location --remote-name https://github.com/Smkz-Entertainment/radar-bench/releases/download/v1.1.1/radar_bench-1.1.1-py3-none-any.whl
    curl --fail --location --remote-name https://github.com/Smkz-Entertainment/radar-bench/releases/download/v1.1.1/radar-bench-decisive-v1.2-evaluator.json
    curl --fail --location --remote-name https://github.com/Smkz-Entertainment/radar-bench/releases/download/v1.1.1/SHA256SUMS
    curl --fail --location --remote-name https://github.com/Smkz-Entertainment/radar-bench/releases/download/v1.1.1/SOURCE-PROVENANCE.json
    grep -E 'radar_bench-1.1.1-py3-none-any.whl|radar-bench-decisive-v1.2-evaluator.json' SHA256SUMS | sha256sum --check
    .venv/bin/python -m pip install --no-deps radar_bench-1.1.1-py3-none-any.whl
    .venv/bin/radar-bench doctor
    .venv/bin/radar-bench list-suites

On Windows, use `.venv\\Scripts\\python.exe` and
`.venv\\Scripts\\radar-bench.exe`; use a trusted SHA-256 verifier if
`sha256sum` is unavailable.

The evaluator asset is not part of the wheel or sdist. Its digest is checked
before it is used, and it remains outside the candidate container. The source
checkout and installed wheel must report the same release version and tag-bound
provenance before evaluation.

## 2. Fetch and verify artifacts

Acquisition is the only phase that may use the network. Store artifacts outside
the repository checkout when possible:

    .venv/bin/radar-bench artifacts fetch --suite decisive-v1.2 --output-root /tmp/radar-artifacts
    .venv/bin/radar-bench artifacts verify --suite decisive-v1.2 --artifact-root /tmp/radar-artifacts

Verification is local-only and fails closed on missing files, changed sizes or
digests, unexpected hosts, unsafe archives, redirects, and extra files.

## 3. Validate the evaluator asset and candidate contract

The evaluator bundle is a host-side input. Validate its structure and the
candidate-visible package contract before starting Docker:

    .venv/bin/radar-bench validate --suite decisive-v1.2 --evaluator-bundle radar-bench-decisive-v1.2-evaluator.json

The command must report a passing bundle audit. Do not copy the file into the
candidate image, candidate working directory, or a Docker mount.

## 4. Invoke the candidate image

Use a full digest-pinned Linux image and the candidate's JSONL protocol command:

    .venv/bin/radar-bench evaluate --suite decisive-v1.2 \
      --artifact-root /tmp/radar-artifacts \
      --candidate-image registry.example/candidate@sha256:<64-hex-digest> \
      --candidate-argv radar-agent --protocol 1.2-jsonl \
      --evaluator-bundle radar-bench-decisive-v1.2-evaluator.json \
      --output result.json

The executor creates fresh opaque episode IDs, runs declared experiment round
trips, denies evaluation networking, bounds resources and output, and checks
cleanup. Candidate output cannot provide case IDs, evaluator labels, gold, or
post-cutoff evidence.

## 5. Verify the result

Always validate the raw result receipt after evaluation:

    .venv/bin/radar-bench verify-results result.json

`COMPLETED` is meaningful only when the receipt contains the required execution
and isolation evidence. Missing artifacts, Docker, platform support, or a
reproducible runtime remains `BLOCKED`; it is not converted into a score.
