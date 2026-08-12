# Radar Bench

Radar Bench is a small, evidence-first executable benchmark for downstream
failure investigation. It is a research benchmark and OSS project, not an
autonomous attribution product.

## Scientific status

The corrected decisive-v1.1 suite preserves the negative product conclusion:

- EXECUTABLE_CAUSAL_SAFETY = VALIDATED_SMALL_N
- HISTORICAL_ATTRIBUTION_EXECUTABILITY = VALIDATED_SMALL_N
- AGENTIC_CAUSAL_INVESTIGATION = FAILED_VALIDATION
- CROSS_REPOSITORY_ATTRIBUTION_PRODUCT = TERMINATED
- AUTONOMOUS_ATTRIBUTION_MVP = DO_NOT_BUILD
- REPLAY_ORACLE_CERTIFICATION = REJECTED
- RADAR_BENCH = VIABLE_OSS_PROJECT

The suite contains five sealed historical cases and twenty opaque safety twins.
It runs the immutable static v0.4 baseline, deterministic naive investigator,
and frozen v0.5 investigator. Results are scored by evaluator-owned gold after
candidate execution; a blocked run is never converted into a score.

The v1.1.0 package adds the separately identified `decisive-v1.2` candidate
protocol. It is a release candidate, not a public benchmark release: candidate
evidence and evaluator gold are physically separate, episode IDs are random per
run, and the tracked release-candidate evidence records completed historical,
safety, canonical, and two clean-clone reproductions. These records do not
replace the independent release audit; publication remains held until that
audit is complete.

## Quickstart

    python -m venv .venv
    python -m pip install .
    radar-bench doctor
    radar-bench validate --suite decisive-v1.2

The v1.2 external candidate interface is deliberately boring. Radar constructs
the Docker sandbox itself from a full digest-pinned image; callers provide only
the image and the candidate argv. The evaluator bundle is supplied separately
and is never mounted into the candidate:

    radar-bench evaluate --suite decisive-v1.2 \
      --candidate-image registry.example/candidate@sha256:<64-hex-digest> \
      --candidate-argv radar-agent --protocol 1.2-jsonl \
      --evaluator-bundle <evaluator-bundle.json>

The installed package contains the candidate-visible contract and schemas.
The evaluator bundle is intentionally a separately supplied evaluator asset;
its absence is an integrity blocker, not a reason to ship gold in the
candidate package.

Acquire and verify the external historical wheelhouses:

    radar-bench artifacts fetch --suite decisive-v1.1 --output-root <artifact-root>
    radar-bench artifacts verify --suite decisive-v1.1 --artifact-root <artifact-root>
    radar-bench evaluate --suite decisive-v1.1 --artifact-root <artifact-root> --output result.json

For the v1.2 catalog use the same acquisition flow with
`--suite decisive-v1.2`. Acquisition may use the network; evaluation must run
after acquisition with network access denied.

Evaluation requires a Linux/x86-64 Docker server with network denial. Docker
Desktop on Windows or macOS is supported only when its server reports the
required Linux engine. Plan for at least 10 GB of free Docker storage, 8 GB
of available memory, 4 CPU cores, and roughly 10 minutes for a cold run;
artifact acquisition is about 277 MB before Docker image layers and temporary
build space. Candidate containers are read-only, network-denied,
capability-dropped, resource-limited, and never receive the Docker socket,
gold labels, or post-cutoff historical evidence.

The external bundles are reconstructed from approved upstream metadata and
verified by size, SHA-256, archive traversal, and sealed-layout checks. They
are not redistributed by this repository. If acquisition or runtime
reconstruction is unavailable, the result remains BLOCKED. The suite is
historical evidence, not a constructed accuracy benchmark; `UNSAFE` is the
expected completed scientific result for the frozen product hypothesis.

## Contract and corrections

decisive-v1.1 is an immutable corrected-suite identity. A03's upstream
reproducer correction is documented in docs/DECISIVE_V1_CORRECTIONS.md; the
original v1.0.0 evidence remains preserved by the immutable v1.0.0 tag.

The v1.2 correction record is under `artifacts/v1.1.0/`; it does not alter the
decisive-v1.1 result, frozen baselines, labels, or tags.

Read docs/QUICKSTART.md, docs/REPRODUCIBILITY.md, docs/THREAT_MODEL.md, and
docs/LIMITATIONS.md before running historical code. Stop and report
`BLOCKED` for missing artifacts, Docker, platforms, or reproducible runtimes;
do not disable network denial or substitute the reference result.

## Scope

Radar Bench does not post GitHub comments, create issues, modify repositories,
apply fixes, or make population-level accuracy claims. The product thesis was
stopped after the decisive frozen-investigator result; the benchmark remains a
reproducible safety and research artifact.

## License

Code and documentation are Apache-2.0. Benchmark metadata, labels, annotations,
and constructed safety twins are CC BY 4.0. See LICENSES.md, DATA_LICENSE.md,
and NOTICE.
