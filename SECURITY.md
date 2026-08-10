# Security policy

Radar Bench executes third-party historical code and untrusted downloaded
archives. Use a disposable Linux/x86-64 Docker environment, keep credentials
outside the workspace, and review artifacts before execution.

The executor uses digest-pinned images, denied networking, read-only roots,
dropped capabilities, no-new-privileges, resource and output limits, fixed
argument arrays, bounded process cleanup, exact artifact inventories, and
evaluator-only gold separation. These controls are defense in depth and are
not a guarantee of multi-tenant isolation.

At the time of this release-candidate audit, this repository has no verified
private vulnerability-reporting channel. Do not put secrets, credentials, or
working exploit details in a public issue. Until the repository owner enables
and verifies a private intake route, open only a minimal public issue asking
the maintainer to establish private follow-up. The release remains blocked on
that external security-channel configuration.
