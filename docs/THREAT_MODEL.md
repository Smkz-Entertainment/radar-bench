# Threat model

Radar Bench executes third-party historical code. Treat issue-derived
metadata, wheel archives, reproducer code, Docker output, and provider output
as untrusted.

## Security properties

- Artifact URLs are HTTPS and host allowlisted after redirects.
- Downloads are bounded, hashed incrementally, checked by exact filename,
  size, archive traversal, CRC, and sealed inventory.
- GitHub URLs reject non-HTTPS schemes, userinfo, ports, queries, backslashes,
  NUL/control characters, percent escaping, and malformed paths.
- Commands are fixed argument arrays; shell interpretation is disabled.
- Subprocess output is streamed under a byte ceiling with digest and bounded
  excerpt; timeouts terminate the process group.
- Docker uses digest-pinned images, Linux/x86-64, network=none, read-only
  roots, dropped capabilities, no-new-privileges, PID/CPU/memory/nofile/core
  limits, and deterministic cleanup.
- Preparation output leaves Docker only through a named volume and an exact
  declared-file inventory. Symlinks, hardlinks, undeclared files, excess
  bytes, and excess file counts are rejected.
- Candidate views contain no gold labels, evaluator fields, post-cutoff
  evidence, host-home mount, or Docker socket.
- Gold is loaded only by the evaluator after candidate lanes finish.

## Operational boundary

The container boundary is defense in depth, not a multi-tenant isolation
guarantee. Use a disposable machine or VM, keep credentials outside the
workspace, review downloaded artifacts, and do not run the suite with
additional mounts or network access.

## Reporting

This repository has no public security email or verified external vulnerability
intake service. The release-candidate audit also found no available private
GitHub vulnerability-reporting endpoint for this repository. Do not put secrets,
credentials, or working exploit details in a public issue. Until the repository
owner enables and verifies a private intake route, open only a minimal public
issue asking the maintainer to establish private follow-up. This is an external
release blocker, not a claim that private reporting is currently available.
