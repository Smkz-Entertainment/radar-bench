# Decisive validation

The v0.7 run used 5 historical attribution cases and 20 executable safety twins with static v0.4, naïve deterministic, and unchanged frozen v0.5 lanes. The frozen investigator reached 1/5 positive resolution, 4/5 candidate-induced correctness, 0/5 action-owner correctness, 20/20 safety abstention, and 0 premature owner accusations. It missed the mandatory scikit-learn #30512 → SciPy resolution.

The result is decisive against the attribution-product thesis. The safety result remains valid at small N. The canonical metrics are preserved in [artifacts/v1.0/canonical-results.json](../artifacts/v1.0/canonical-results.json) as reference-only evidence.
