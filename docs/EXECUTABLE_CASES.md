# Executable cases

An executable historical case must contain the downstream revision, exact control and candidate dependency environments, all local wheels or source artifacts, a digest-pinned container, a minimal reproducer, independent control/candidate runs, and fresh reruns. Network access is denied during evaluation.

The five promoted cases are listed in `corpus/v0.7/decisive-v1/suite.json`. Their manifests record the original staging paths and hashes; a public checkout without those paths must report `ARTIFACT_UNAVAILABLE`.
