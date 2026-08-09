# Reproducibility

1. Check out the exact release commit.
2. Install with `python -m pip install .`.
3. Run `radar-bench validate --suite decisive-v1`.
4. Provide the exact locally sealed wheelhouses under an external artifact root and run `radar-bench evaluate --suite decisive-v1 --artifact-root /path/to/radar-bench-artifacts`. The Docker server, rather than the client host OS, must report Linux/x86-64.
5. Preserve the machine result, suite/source hashes, Docker image digest, and release audit files.

If any artifact, platform, Docker runtime, schema, or hash check fails, retain the blocked result and its rejection reason.
