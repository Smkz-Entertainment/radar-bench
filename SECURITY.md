# Security policy

Radar Bench executes third-party historical code. Treat every executable case and artifact bundle as untrusted.

## Runtime boundary

The supported canonical runtime is Linux/x86-64 with Docker. A case executor must use a digest-pinned image, `--network=none`, read-only workspace mounts, a private scratch filesystem, dropped capabilities, no privileged mode, no Docker socket, no host-home mount, explicit environment variables, and resource/time limits. Do not run the executable suite on a host whose Docker daemon or mount policy you have not reviewed.

The container boundary is a defense-in-depth measure, not a proof of perfect isolation. Keep secrets, SSH agents, cloud credentials, source checkouts, and personal files outside the execution environment. Do not add network access to make a case pass.

## Reporting

Do not publish secret-bearing logs, artifact contents, or exploit details. For a suspected vulnerability, contact the project maintainers through the private project security channel when one is configured. If no private channel is available, open a minimal public issue containing only a non-sensitive description and state that more detail is available privately.

## Supply chain

Use the lock/hash information in sealed manifests, inspect third-party code before execution, run the repository security checks, and preserve the exact image and artifact digests in release evidence. A missing or mismatched artifact is a blocked case, never an invitation to download a replacement during evaluation.

GitHub Actions are pinned to full commit SHAs, use explicit token permissions, and do not run privileged code from `pull_request_target`. Dependabot tracks both action and Python dependency updates. Review workflow changes as supply-chain-sensitive code.
