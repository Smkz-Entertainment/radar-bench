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

## Quickstart

    python -m venv .venv
    python -m pip install .
    radar-bench doctor
    radar-bench validate --suite decisive-v1.1

Acquire and verify the external historical wheelhouses:

    radar-bench artifacts fetch --suite decisive-v1.1 --output-root <artifact-root>
    radar-bench artifacts verify --suite decisive-v1.1 --output-root <artifact-root>
    radar-bench evaluate --suite decisive-v1.1 --artifact-root <artifact-root> --output result.json

Evaluation requires a Linux/x86-64 Docker server with network denial. Docker
Desktop on Windows or macOS is supported only when its server reports the
required Linux engine. Candidate containers are read-only, network-denied,
capability-dropped, resource-limited, and never receive the Docker socket,
gold labels, or post-cutoff historical evidence.

The external bundles are reconstructed from approved upstream metadata and
verified by size, SHA-256, archive traversal, and sealed-layout checks. They
are not redistributed by this repository. If acquisition or runtime
reconstruction is unavailable, the result remains BLOCKED.

## Contract and corrections

decisive-v1.1 is an immutable corrected-suite identity. A03's upstream
reproducer correction is documented in docs/DECISIVE_V1_CORRECTIONS.md; the
original v1.0.0 evidence remains preserved by the immutable v1.0.0 tag.

Read docs/QUICKSTART.md, docs/REPRODUCIBILITY.md, docs/THREAT_MODEL.md, and
docs/LIMITATIONS.md before running historical code.

## Scope

Radar Bench does not post GitHub comments, create issues, modify repositories,
apply fixes, or make population-level accuracy claims. The product thesis was
stopped after the decisive frozen-investigator result; the benchmark remains a
reproducible safety and research artifact.

## License

Code and documentation are Apache-2.0. Benchmark metadata, labels, annotations,
and constructed safety twins are CC BY 4.0. See LICENSES.md, DATA_LICENSE.md,
and NOTICE.
