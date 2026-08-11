# Releasing

The v1.1.0 branch is a release candidate only when all gates are backed by
machine-readable evidence. Keep the v1.0.0 tag immutable and do not move the
private v1.0.1 candidate tag.

Before tagging:

1. verify the package version, legal files, citation, and changelog;
2. run unit tests, coverage, Ruff, mypy, Bandit, pip-audit, and secret scans;
3. build and smoke-test the wheel and sdist from an empty directory;
4. validate strict schemas and the v1.1.0 `decisive-v1.2` suite;
5. run two independent clean-clone reproductions when Docker and artifacts are
   available;
6. confirm the expected negative scientific conclusion and the mandatory
   #30512-to-SciPy gate;
7. require a clean git diff --check and clean worktree;
8. create no tag or GitHub Release in this phase. Tag migration is a separate
   approved operation after the candidate gates pass.

If an external artifact or platform is unavailable, record BLOCKED and do not
tag. A release can publish the OSS benchmark contract while retaining the
canonical suite's fail-closed status; it must not claim end-to-end
reproducibility without the runtime evidence.

The repository does not run an automatic GitHub Release job. The manual
workflow verifies an explicitly supplied tag and build only; it never creates
or moves a tag and never publishes a release. The repository remains private
until the owner chooses publication visibility. A source push is not a
scientific release and must not be described as one.
