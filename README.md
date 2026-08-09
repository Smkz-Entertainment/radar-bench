# Radar Bench 1.0.0

Radar Bench is an evidence-first, executable benchmark for downstream failure investigation. It is an OSS benchmark and research record—not an autonomous attribution product.

## Final scientific status

The v0.7 decisive run found real executable safety evidence, but the frozen investigator failed the product hypothesis: it resolved only 1/5 historical positives, missed the required scikit-learn #30512 → SciPy cross-repository case, and did not establish action-owner correctness. The replay oracle was rejected after v0.6 exposed gold leakage.

Therefore:

| Decision | Status |
|---|---|
| `EXECUTABLE_CAUSAL_SAFETY` | `VALIDATED_SMALL_N` |
| `HISTORICAL_ATTRIBUTION_EXECUTABILITY` | `VALIDATED_SMALL_N` |
| `AGENTIC_CAUSAL_INVESTIGATION` | `FAILED_VALIDATION` |
| `CROSS_REPOSITORY_ATTRIBUTION_PRODUCT` | `TERMINATED` |
| `AUTONOMOUS_ATTRIBUTION_MVP` | `DO_NOT_BUILD` |
| `REPLAY_ORACLE_CERTIFICATION` | `REJECTED` |
| `RADAR_BENCH` | `VIABLE_OSS_PROJECT` |

## Quickstart

Install the package in a virtual environment, then validate the public suite:

```text
python -m pip install .
radar-bench --version
radar-bench validate --suite decisive-v1
```

The supported evaluation command is:

```text
radar-bench evaluate --suite decisive-v1 --output artifacts/v1.0/result.json
```

The canonical executable suite requires a Linux/x86-64 Docker engine with network denial. Docker Desktop on Windows or macOS is acceptable when its server engine reports those capabilities. Historical wheelhouses are external inputs; provide them with `--artifact-root` when available. Without them, the command fails closed and records `ARTIFACT_UNAVAILABLE`. `canonical-results.json` is a reference artifact, never a substitute for execution.

## decisive-v1

The suite contains five sealed historical cases and twenty opaque executable safety twins. It evaluates the frozen static v0.4 baseline, a deterministic naïve investigator, and unchanged v0.5 behavior from commit `60ccc18`. Candidate containers have no network, no gold labels, no historical discussion, no host-home mount, and no Docker socket.

Start with [docs/QUICKSTART.md](docs/QUICKSTART.md), then read [docs/DECISIVE_VALIDATION.md](docs/DECISIVE_VALIDATION.md) and [BENCHMARK.md](BENCHMARK.md).

Maintainer release procedures are in [docs/RELEASING.md](docs/RELEASING.md). GitHub Actions are configured for least-privilege CI, immutable action references, dependency update automation, and draft-only release creation after all gates pass.

## Scope and limitations

Radar Bench measures reproducibility, temporal blindness, executable safety, and bounded causal reasoning on a small corpus. It makes no population-level accuracy claim, has no production integration, does not post GitHub comments, and does not autonomously modify code. The historical bundles are intentionally not redistributed by this repository; a clean checkout must report their absence rather than silently falling back to replay.

The v0.1–v0.7 research record remains in the repository and is summarized in [docs/RESEARCH_HISTORY.md](docs/RESEARCH_HISTORY.md).

## License

Apache-2.0. Third-party projects and incident sources retain their own copyrights and licenses. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
