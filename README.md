# Radar Bench

Radar Bench is a small, evidence-first executable benchmark for downstream
failure investigation. Its differentiator is the execution boundary: controls,
candidate observations, evaluator-owned labels, and reproducibility receipts are
separate artifacts, and missing or unsafe inputs fail closed.

## Repository layout

Radar keeps versioned benchmark material visible so that historical results and
current releases remain reproducible:

- `candidate/decisive-v1.2/` — the current candidate-visible contract.
- `evaluator/decisive-v1.2/` — the current evaluator-only source.
- `corpus/v1.1.0/decisive-v1.2/` — the immutable current suite definition.
- `corpus/v1.0.1/` — historical reproducers and runtime fixtures still used by
  the current benchmark.
- `baselines/` and `reference/` — frozen historical reference material and
  negative results.
- `evidence/` — retained scientific and provenance receipts.

## What it measures

Radar measures whether an investigator can distinguish candidate-induced failure
from dependency, packaging, platform, resolver, nondeterministic, and external
resource failure under bounded, network-denied execution. The current package
suite is `decisive-v1.2`, a 25-case protocol with five historical cases and
twenty constructed safety twins. `decisive-v1.1` is the preserved historical
reference suite and remains available for regression reproduction.

The v1.1 line preserves the negative product result:

- `EXECUTABLE_CAUSAL_SAFETY = VALIDATED_SMALL_N`
- `HISTORICAL_ATTRIBUTION_EXECUTABILITY = VALIDATED_SMALL_N`
- `AGENTIC_CAUSAL_INVESTIGATION = FAILED_VALIDATION`
- `CROSS_REPOSITORY_ATTRIBUTION_PRODUCT = TERMINATED`
- `AUTONOMOUS_ATTRIBUTION_MVP = DO_NOT_BUILD`

These are small-sample research results, not population estimates or product
accuracy claims. Radar does not provide an attribution agent, automatic fixes,
GitHub comments, issue creation, SaaS tenancy, or an external inference service.

## v1.1 and v1.2

`decisive-v1.1` is the corrected historical reference contract used to preserve
the five sealed cases, frozen baselines, and the original negative conclusion.
`decisive-v1.2` is the current package suite: it adds opaque per-run episode IDs,
the fail-closed external JSONL candidate protocol, fresh experiment accounting,
and evaluator/candidate separation. It does not change the cases, labels, gold,
scoring, or frozen baseline behavior.

## Verified installation

The versioned release wheel is the preferred installation input. For a published
version, download the wheel and matching `SHA256SUMS` release asset, verify the
digest, and then install it:

    python -m venv .venv
    .venv/bin/python -m pip install --no-deps radar_bench-<version>-py3-none-any.whl
    .venv/bin/radar-bench doctor
    .venv/bin/radar-bench list-suites

On Windows, use `.venv\\Scripts\\python.exe` and
`.venv\\Scripts\\radar-bench.exe`. Published releases in the v1.1 line list
their exact source provenance; use the matching version tag and release assets
when verifying a release.

## v1.2 quickstart

The complete tested workflow is [docs/QUICKSTART.md](docs/QUICKSTART.md). It
installs the release wheel, fetches and verifies external artifacts, downloads
and verifies the evaluator-only bundle, invokes a digest-pinned candidate image,
writes a result, and runs `verify-results`. The evaluator asset is never copied
into the wheel or mounted into the candidate container.

The short form is:

    radar-bench artifacts fetch --suite decisive-v1.2 --output-root <artifact-root>
    radar-bench artifacts verify --suite decisive-v1.2 --artifact-root <artifact-root>
    radar-bench evaluate --suite decisive-v1.2 --artifact-root <artifact-root> \
      --candidate-image registry.example/candidate@sha256:<64-hex-digest> \
      --candidate-argv radar-agent --protocol 1.2-jsonl \
      --evaluator-bundle radar-bench-decisive-v1.2-evaluator.json \
      --output result.json
    radar-bench verify-results result.json

For the preserved `decisive-v1.1` reference regression, acquire its external
wheelhouses and run the historical contract explicitly:

    radar-bench artifacts fetch --suite decisive-v1.1 --output-root <artifact-root>
    radar-bench artifacts verify --suite decisive-v1.1 --artifact-root <artifact-root>
    radar-bench evaluate --suite decisive-v1.1 --artifact-root <artifact-root> --output result.json
    radar-bench verify-results result.json

Acquisition may use the network. Evaluation must run with Docker networking
denied (`network-denied`). If all required historical inputs execute, the frozen
reference's expected completed scientific status is `UNSAFE`; if an artifact,
platform, or runtime is unavailable, the result is `BLOCKED`. A reference file
is never substituted for execution.

## Security warning

The benchmark executes third-party historical code and downloaded archives. Use
a disposable Linux/x86-64 machine or VM, review inputs, keep credentials outside
the workspace, and do not add mounts or network access. Docker controls are
defense in depth, not a guarantee of multi-tenant isolation. Report sensitive
vulnerabilities through [private GitHub Security Advisories](https://github.com/Smkz-Entertainment/radar-bench/security/advisories/new),
not a public issue.

## Limitations

Read [docs/LIMITATIONS.md](docs/LIMITATIONS.md) before interpreting results. In
particular, the suite has small N, a strong Python/pandas concentration, limited
cross-repository coverage, a constructed safety set, public-gold memorization
risk, no hidden tests, and limited platform/ecosystem generalization.

## Citation and contribution

Use [CITATION.cff](CITATION.cff) for citation metadata. Contributions should
follow [CONTRIBUTING.md](CONTRIBUTING.md), preserve candidate/gold separation,
and include the full validation evidence. Questions and reproducibility help
belong in the [support issue form](https://github.com/Smkz-Entertainment/radar-bench/issues/new?template=support.yml).

## License

Code and documentation are Apache-2.0. Benchmark metadata, labels, annotations,
and constructed safety twins are CC BY 4.0. See [LICENSES.md](LICENSES.md),
[DATA_LICENSE.md](DATA_LICENSE.md), and [NOTICE](NOTICE).
