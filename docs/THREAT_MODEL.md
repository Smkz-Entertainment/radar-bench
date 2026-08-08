# Threat model

## Attacker and harm

Assume a malicious or stale issue body, comment, log, repository file, package
metadata field, redirect, case record, or provider output. Harms include false
upstream blame, secret leakage, prompt/command injection, SSRF, path traversal,
gold-label leakage, model certainty inflation, and unsafe repository execution.

## Controls

- GitHub access is HTTPS, allowlisted, read-only, token-from-environment only,
  and redirect-checked; writes and maintainer notifications do not exist.
- Evidence is structured, size-limited, digest-checked, atomically stored, and
  indexed with retrieval/ETag/cutoff metadata. Raw logs are not default data.
- Temporal filters fail closed; input and gold are separate; providers cannot
  load gold paths.
- Provider and experiment commands are arrays, never shell strings. No shell
  construction, pickle, unsafe YAML, eval, or arbitrary executor is used.
- CAS paths are validated; output paths reject absolute and parent traversal.
- Redaction removes common authorization/key/token patterns before excerpts
  are persisted. Secrets are never copied from headers or cookies.
- Predictions require strict schemas and cited inference-visible evidence.
  Model self-confidence cannot upgrade a result.
- Corrections/retractions are explicit; security-sensitive findings stay
  private; no AI-only conclusion contacts maintainers.

The optional container executor is not included in v0.1, so no claim of a
hardened multi-tenant sandbox is made.

