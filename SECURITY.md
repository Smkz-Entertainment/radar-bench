# Security policy

Radar Bench executes third-party historical code, downloaded archives, and
untrusted candidate output. Use a disposable Linux/x86-64 machine or VM, keep
credentials outside the workspace, and inspect artifacts before execution.

The executor uses digest-pinned images, denied networking, read-only roots,
dropped capabilities, no-new-privileges, resource and output limits, fixed
argument arrays, bounded process cleanup, exact artifact inventories, and
evaluator-only gold separation. These controls are defense in depth and are not
a guarantee of multi-tenant isolation.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/Smkz-Entertainment/radar-bench/security/advisories/new)
for sensitive reports. Do not put secrets, credentials, private artifact bundles,
or working exploit details in a public issue. Include the affected version or
commit, a minimal reproduction, impact, and any safe mitigation. The maintainer
will coordinate disclosure and credit reporters who want attribution.

## Research and execution boundary

The public package contains candidate-visible schemas, runtime fixtures, and
reproducers. The evaluator asset is separately distributed, host/evaluator-only,
and must never be mounted into a candidate container. The benchmark does not
claim multi-tenant sandbox security, hidden-test protection, or production
deployment safety.
