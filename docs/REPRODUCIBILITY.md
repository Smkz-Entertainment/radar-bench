# Reproducibility contract

Radar Bench distinguishes three gates:

1. Artifact reproducibility: another machine obtains exactly the required
   inputs and verifies their hashes.
2. Historical runtime reproducibility: another machine reconstructs all five
   control/candidate environments from digest-pinned recipes.
3. Benchmark reproducibility: a clean checkout runs all 25 cases with network
   denial and reproduces the strict result contract.

A pass at an earlier gate never substitutes for a later gate.

## Clean-clone procedure

From a brand-new checkout with no developer caches:

    python -m pip install .
    radar-bench artifacts fetch --suite decisive-v1.1 --output-root <artifact-root>
    radar-bench artifacts verify --suite decisive-v1.1 --output-root <artifact-root>
    radar-bench evaluate --suite decisive-v1.1 --artifact-root <artifact-root> --output result.json
    radar-bench verify-results result.json

The evaluation machine must provide a Linux/x86-64 Docker server. Disconnect
the execution network after acquisition. Compare metric numerators,
denominators, case predictions, mandatory gates, suite digest, runtime recipe
digest, and artifact bundle digests. Run the clean-clone procedure twice from
destroyed temporary state.

Missing artifacts, unavailable platforms, unreproducible historical builds,
unarchived dependencies, nondeterminism, and unavailable hardware remain
blocked outcomes. They must not be replaced by a reference result or a new
case under the same suite identity.
