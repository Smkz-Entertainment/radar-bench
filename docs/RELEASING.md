# Releasing

The v1.0.1 release branch is release-grade only when all gates are backed by
machine-readable evidence. Keep the v1.0.0 tag immutable.

Before tagging:

1. verify the package version, legal files, citation, and changelog;
2. run unit tests, coverage, Ruff, mypy, Bandit, pip-audit, and secret scans;
3. build and smoke-test the wheel and sdist from an empty directory;
4. validate strict schemas and the v1.0.1 suite;
5. run two independent clean-clone reproductions when Docker and artifacts are
   available;
6. confirm the expected negative scientific conclusion and the mandatory
   #30512-to-SciPy gate;
7. require a clean git diff --check and clean worktree;
8. create only an annotated local v1.0.1 tag after the gates pass.

If an external artifact or platform is unavailable, record BLOCKED and do not
tag. A release can publish the OSS benchmark contract while retaining the
canonical suite's fail-closed status; it must not claim end-to-end
reproducibility without the runtime evidence.

This repository intentionally does not run an automatic GitHub Release job.
The repository remains private until the owner chooses publication visibility;
the annotated tag and release assets must be created only after the evidence
listed above is reviewed. A public source push is not a scientific release and
must not be described as one.
