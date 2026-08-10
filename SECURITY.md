# Security policy

Radar Bench executes third-party historical code and untrusted downloaded
archives. Use a disposable Linux/x86-64 Docker environment, keep credentials
outside the workspace, and review artifacts before execution.

The executor uses digest-pinned images, denied networking, read-only roots,
dropped capabilities, no-new-privileges, resource and output limits, fixed
argument arrays, bounded process cleanup, exact artifact inventories, and
evaluator-only gold separation. These controls are defense in depth and are
not a guarantee of multi-tenant isolation.

For a sensitive vulnerability report, use the private GitHub repository
security channel. No public security email address is claimed by this
project. If that channel is unavailable, open a minimal public issue without
secrets or exploit details and request private follow-up.
