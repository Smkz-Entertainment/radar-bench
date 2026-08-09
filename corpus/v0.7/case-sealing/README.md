# v0.7 case-sealing sprint

This directory records the first real historical reconstruction attempts. It
is case evidence, not a new benchmark executor and not an evaluation result.

Rules used for this sprint:

- A case is sealed only after independent control and candidate containers
  reproduce the historical distinction with `--network none`.
- Candidate containers receive only the pre-cutoff input and local runtime
  artifacts. Gold, post-cutoff discussion, and control output are not mounted.
- A failed reconstruction is recorded with an explicit rejection reason; it is
  never converted into a synthetic or replay-only case.
- The v0.7 executable manifest remains unchanged until the pilot minimum of
  three attribution and five safety cases is actually met.

The local artifact bundles used for this run are retained outside Git under the
external bundle ID recorded in the sealed manifest. Their SHA-256 values
are recorded in the sealed case manifests.

Current sprint result: 3 locally sealed attribution cases, 0 locally sealed
safety cases, 5 safety cases rejected with evidence. Radar framework code was
not changed.
