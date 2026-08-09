# Executable cases

An executable historical case must contain the downstream revision, exact control and candidate dependency environments, all local wheels or source artifacts, a digest-pinned container, a minimal reproducer, independent control/candidate runs, and fresh reruns. Network access is denied during evaluation.

The five promoted cases are listed in `corpus/v0.7/decisive-v1/suite.json`. Their public manifests contain content-addressed file hashes and non-sensitive bundle IDs, never developer-local paths. A clean checkout must receive the externally staged bundles explicitly:

```text
radar-bench evaluate --suite decisive-v1 --artifact-root /path/to/radar-bench-artifacts
```

The artifact root must contain one directory per bundle ID recorded in the manifests. The evaluator verifies every file digest before execution and reports `ARTIFACT_UNAVAILABLE` when the root is absent or incomplete.
