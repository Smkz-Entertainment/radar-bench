# Case sealing sprint report

Date: 2026-08-09

Twenty-two historical candidates have now been screened using the existing
v0.4 records and primary incident pages. Five attribution cases were
reconstructed with digest-pinned local containers:

| case | control | candidate | result |
| --- | ---: | ---: | --- |
| pandas #55137 | 0 | 1 | pandas 1.3.4 pickle cannot be read by 2.1.0 |
| scikit-learn #30512 | 0 | 1 | SciPy 1.15.0rc1 breaks SplineTransformer pickle check |
| pandas #45601 | 0 | 1 | pandas 1.4.0 leaves nullable `pd.NA` unchanged |
| pandas #57124 | 0 | 1 | pandas 2.2.0 emits the issue's FutureWarning |
| pandas #66085 | 0 | 139 | pandas 3.0.4 segfaults on the duplicated ISO8601 reproducer |

The first three use Python 3.10 Linux/x86-64 wheels and the digest-pinned local container
`mirror.gcr.io/library/python@sha256:63669fd2563fa90b0442fa7b568e66e3667755636cda086d7bcaaa895f66fe39`.
The pandas #66085 case uses Python 3.13 Linux/x86-64 and its digest-pinned
container is recorded in its sealed manifest.

Each sealed case passed two fresh control/candidate reruns with Docker network
mode `none`:

| case | control | candidate | result |
| --- | ---: | ---: | --- |
| pandas #55137 | 0 | 1 | pandas 1.3.4 pickle cannot be read by 2.1.0 |
| scikit-learn #30512 | 0 | 1 | SciPy 1.15.0rc1 breaks SplineTransformer pickle check |
| pandas #45601 | 0 | 1 | pandas 1.4.0 leaves nullable `pd.NA` unchanged |
| pandas #57124 | 0 | 1 | pandas 2.2.0 emits the issue's FutureWarning |
| pandas #66085 | 0 | 139 | pandas 3.0.4 segfaults on duplicated ISO8601 input |

The candidate containers were given only local wheels and the pre-cutoff input.
Gold, post-cutoff discussion, and control output were not mounted. The full
wheel SHA-256 inventory and external bundle IDs are in the adjacent JSON files;
developer-local staging paths are intentionally excluded from the public record.

The recommended scikit-learn #30554 case was rejected with
`PLATFORM_UNAVAILABLE`: the historical report is macOS arm64, while the
available Linux/x86-64 downstream replay did not reproduce the changed tree,
and the available downstream wheel carried an incompatible `scikit-learn<1.6`
requirement. This is evidence against promotion, not a failed benchmark pass.

Five safety controls were examined and rejected rather than synthesized:

- xarray #10709: `ARTIFACT_UNAVAILABLE` for the external URL/response and
  historical dependency closure.
- scikit-learn #34458: `ARTIFACT_UNAVAILABLE` for the missing nightly wheel and
  its exact index snapshot.
- scikit-learn #34578: `NONDETERMINISTIC` because failures vary by seed.
- xarray #11268: `DEPENDENCY_NOT_ARCHIVED` for the historical pixi cache and
  package-index state.
- xarray #11330: `ARTIFACT_UNAVAILABLE` because the baseline's stale cached
  lock was not committed or archived.

The first-batch target is therefore not met: 5/3 attribution, 0/5 safety.
`corpus/v0.7/executable-subset.json` remains intentionally unsealed with zero
cases, and commit `60ccc18` has not been run as a product-validation result.
No Radar framework or executor code was changed.
