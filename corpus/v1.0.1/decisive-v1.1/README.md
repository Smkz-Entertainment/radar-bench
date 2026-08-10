# decisive-v1.1

`decisive-v1.1` is the corrected Radar Bench executable benchmark contract:

- five sealed historical attribution cases;
- twenty opaque constructed safety twins;
- the static v0.4 baseline, deterministic naive baseline, and unchanged v0.5 investigator;
- network-denied, digest-pinned Linux/x86-64 Docker execution;
- evaluator-only labels physically outside candidate-visible runtime trees;
- one case-agnostic executor harness and one opaque candidate protocol for both lanes.

The five historical wheelhouses are not redistributed in this repository. Their sealed manifests contain bundle IDs and file hashes, but no developer-local staging paths. Supply the bundles from an external artifact root:

```text
radar-bench evaluate --suite decisive-v1.1 --artifact-root /path/to/radar-bench-artifacts
```

A clean checkout without that root validates the suite contract but must report `ARTIFACT_UNAVAILABLE`. It must never treat `artifacts/v1.0/canonical-results.json` as a live run.

Artifact, execution, and benchmark reproducibility are separate gates:

- artifact reproducibility: another machine can acquire and verify the exact wheelhouses;
- execution reproducibility: Docker can rebuild both sides from `runtime-recipes.json` and replay all five controls/candidates;
- benchmark reproducibility: the complete five-attribution plus twenty-safety decisive run reproduces its frozen result.

The first gate can pass while either of the latter gates remains `BLOCKED`. The runtime recipes pin the base image digest, exact Python version, package wheels, filesystem layout, preparation, command, expected exits, and network-denied execution policy. The harness loads evaluator labels only after candidate lanes finish; labels and gold evidence never enter a candidate view.

The harness is deliberately not an investigator. It does not select case-specific experiments, translate failures into hints, use the canonical reference as runtime evidence, or silently skip unsupported experiments. A successful run can still be certified `UNSAFE`: that means the executable benchmark ran, but the agentic attribution thesis did not meet its scientific gate.

The supported acquisition path is:

```text
radar-bench artifacts fetch --suite decisive-v1.1
radar-bench artifacts verify --suite decisive-v1.1
```

Run structural validation with:

```text
radar-bench validate --suite decisive-v1.1
```

Run the supported evaluation command with:

```text
radar-bench evaluate --suite decisive-v1.1 --artifact-root /path/to/radar-bench-artifacts --output /path/to/evaluation.json
```

The command fails closed when the Docker server does not provide Linux/x86-64, network denial, or sealed historical artifacts.
