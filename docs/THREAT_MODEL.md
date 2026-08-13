# Threat model

Radar executes third-party historical code, wheel archives, Docker output, and
candidate/provider output. Treat all of those inputs as untrusted.

## Security properties

- artifact URLs are HTTPS and host-allowlisted after redirects;
- downloads are bounded, incrementally hashed, and checked by exact filename,
  size, archive traversal, CRC, and sealed inventory;
- commands are fixed argument arrays with shell interpretation disabled;
- subprocess output is streamed under a byte ceiling and timeouts terminate the
  process group;
- Docker uses digest-pinned images, Linux/x86-64, `network=none`, read-only roots,
  dropped capabilities, no-new-privileges, PID/CPU/memory/nofile/core limits,
  and deterministic cleanup;
- preparation output leaves Docker only through a named volume and an exact
  declared-file inventory;
- symlinks, hardlinks, undeclared files, excess bytes, and excess file counts are
  rejected;
- candidate views contain no gold labels, evaluator fields, post-cutoff
  evidence, host-home mount, or Docker socket;
- Gold is loaded only by the evaluator after candidate lanes finish.

## Operational boundary

These controls are defense in depth, not a multi-tenant isolation guarantee. Use
a disposable machine or VM, keep credentials outside the workspace, review
downloaded artifacts, and do not run with additional mounts or network access.
The evaluator asset is a host-side input and is never mounted into the candidate
container.

## Reporting

Report sensitive vulnerabilities through [private GitHub Security Advisories](https://github.com/Smkz-Entertainment/radar-bench/security/advisories/new).
Public issues are appropriate for sanitized reproducible defects, documentation,
and support questions only.
