# Historical artifact acquisition

The five decisive historical cases require external wheelhouses. The public
repository does not redistribute those bytes. The catalog at
`corpus/v0.7/decisive-v1/artifact-catalog.json` records each bundle's case
mapping, architecture, format, expected file paths, byte sizes, file digests,
aggregate digest, upstream provenance, and reconstruction status.

All five bundles are currently classified `RECONSTRUCT_ONLY`. That is not a
third-party redistribution-rights claim. It means the exact files may be
acquired from the approved PyPI release metadata and must be verified locally;
no downloaded bytes are committed or published by this repository.

From a clean checkout:

```text
radar-bench artifacts fetch --suite decisive-v1
radar-bench artifacts verify --suite decisive-v1
radar-bench evaluate --suite decisive-v1 --artifact-root artifacts/external/decisive-v1
```

`fetch` uses only HTTPS PyPI metadata and PyPI file hosts, rejects unexpected
hosts, enforces recorded sizes, verifies SHA-256 digests, validates wheel
archives for traversal and corruption, rejects unexpected bundle entries, and
writes only to the ignored external artifact root. `verify` is local-only and
does not contact the network.

The final evaluation still requires executable `runtime_recipe` fields for the
historical cases. Artifact acquisition alone must therefore not be interpreted
as canonical historical execution or as a release pass.
