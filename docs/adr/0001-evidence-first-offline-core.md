# ADR 0001: evidence-first offline core

## Decision

Radar v0.1 uses a standard-library Python core with repository-owned JSON
schemas, deterministic validators, and optional network adapters. No provider
or model is trusted to repair invalid evidence or silently upgrade confidence.

## Rationale

Offline checks are reproducible on the current machine and remain available
when public services are unavailable. The cost is that richer third-party
tooling is optional rather than a release prerequisite.

