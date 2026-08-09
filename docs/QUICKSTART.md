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

Evaluate only on the supported Linux/x86-64 Docker platform:

```text
radar-bench evaluate --suite decisive-v1 --output artifacts/v1.0/result.json
```

On Windows, macOS, missing Docker, or missing sealed wheelhouses, the command returns a non-zero blocked result. That is expected and must not be converted into a score.
