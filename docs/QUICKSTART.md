# Quickstart

Install from a clean checkout:

```text
python -m venv .venv
python -m pip install .
radar-bench --version
```

Validate the suite contract:

```text
radar-bench validate --suite decisive-v1
```

Evaluate only with a supported Linux/x86-64 Docker engine (Docker Desktop's Linux engine is acceptable):

```text
radar-bench evaluate --suite decisive-v1 --output artifacts/v1.0/result.json
```

Without Docker, without a Linux/x86-64 Docker server, or without externally staged wheelhouses, the command returns a non-zero blocked result. That is expected and must not be converted into a score.

To reconstruct and verify the external historical inputs, see
[ARTIFACTS.md](ARTIFACTS.md). Artifact acquisition does not change the
fail-closed canonical release gate.
