# Reproducibility contract

Radar separates three gates:

1. artifact reproducibility: another machine obtains the exact required inputs
   and verifies their hashes;
2. historical runtime reproducibility: another machine reconstructs all five
   control/candidate environments from digest-pinned recipes;
3. benchmark reproducibility: a clean checkout runs the 25-case contract with
   evaluation networking denied and validates the strict result receipt.

A pass at an earlier gate never substitutes for a later gate. The current v1.2
package suite and the preserved v1.1 reference use the same fail-closed rule for
missing artifacts, unavailable platforms, unreproducible historical builds,
unarchived dependencies, nondeterminism, and unavailable hardware.

## Clean-clone procedure

From a new checkout with no developer caches:

    python -m pip install --no-deps radar_bench-1.1.1-py3-none-any.whl
    radar-bench artifacts fetch --suite decisive-v1.2 --output-root <artifact-root>
    radar-bench artifacts verify --suite decisive-v1.2 --artifact-root <artifact-root>
    radar-bench validate --suite decisive-v1.2 --evaluator-bundle <evaluator-bundle>
    radar-bench evaluate --suite decisive-v1.2 --artifact-root <artifact-root> \
      --candidate-image <digest-pinned-image> \
      --candidate-argv <candidate-command> --protocol 1.2-jsonl \
      --evaluator-bundle <evaluator-bundle> --output result.json
    radar-bench verify-results result.json

Destroy temporary artifacts and repeat from the exact same commit for a second
clone. Compare suite, candidate bundle, runtime, artifact, result, and package
digests. The evaluator asset stays on the host and is never mounted into the
candidate boundary.

## Historical reference regression

The `decisive-v1.1` suite remains available for regression checks. Its sealed
five-case artifacts are external inputs; its frozen baselines and canonical
negative result are preserved. A blocked historical case is evidence about
reproducibility limits, not a correct or incorrect investigator prediction.
