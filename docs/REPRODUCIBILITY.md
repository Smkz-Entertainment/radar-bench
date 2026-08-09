# Reproducibility

1. Check out the exact release commit.
2. Install with `python -m pip install .`.
3. Run `radar-bench validate --suite decisive-v1`.
4. Provide the exact locally sealed wheelhouses under an external artifact root and run `radar-bench evaluate --suite decisive-v1 --artifact-root /path/to/radar-bench-artifacts`. The Docker server, rather than the client host OS, must report Linux/x86-64.
5. From a clean clone, run `radar-bench artifacts fetch --suite decisive-v1` and `radar-bench artifacts verify --suite decisive-v1` before evaluation. Preserve the machine result, catalog digest, bundle digests, suite/source hashes, Docker image digest, and release audit files.

Artifact reconstruction is only the first gate. The evaluation must separately
reconstruct all five historical control/candidate runtimes from the digest-pinned
recipes, then run the complete decisive-v1 suite. A passing artifact check must
not be reported as passing execution or benchmark reproducibility.

If any artifact, platform, Docker runtime, schema, or hash check fails, retain the blocked result and its rejection reason.
