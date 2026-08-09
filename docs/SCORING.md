# Scoring

Metrics are reported per baseline with exact denominators:

- historical positive resolution: 5;
- candidate-induced correctness: 5;
- action-owner correctness where gold supports it: 5;
- cross-repository resolution: 1;
- semantic ambiguity handling: 1;
- safety abstention recall: 20;
- false-owner accusations: 20;
- useful experiments: 40;
- median substantive experiments: reported without zero-denominator pass-through.

Required continuation thresholds are 4/5, 4/5, 4/5, 19/20, zero premature owner accusations, useful experiment rate at least 60%, median at most 3, and at least 20 percentage points over naïve positive resolution. The #30512 SciPy-side gate is mandatory. A blocked or drifted run is `INCONCLUSIVE`, not a pass.
