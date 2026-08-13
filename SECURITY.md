# Security policy

Radar Bench executes third-party historical code and untrusted downloaded
archives. Use a disposable Linux/x86-64 Docker environment, keep credentials
outside the workspace, and review artifacts before execution.

The executor uses digest-pinned images, denied networking, read-only roots,
dropped capabilities, no-new-privileges, resource and output limits, fixed
argument arrays, bounded process cleanup, exact artifact inventories, and
evaluator-only gold separation. These controls are defense in depth and are
not a guarantee of multi-tenant isolation.

Release-candidate evidence for v1.1.0 may include fresh historical and safety
execution, a completed isolated candidate protocol, and clean-clone
reproductions. Those records establish reproducibility evidence but do not
constitute independent release approval or public publication.

Before public publication, the repository owner must establish and verify a
private vulnerability-reporting channel. Do not put secrets, credentials, or
working exploit details in a public issue. If a private intake route is not
available, open only a minimal public issue asking the maintainer to establish
private follow-up; a state with no verified private channel is not
publication-ready, and a release remains blocked until that channel and the
independent release audit are complete.
