# Methodology

Radar Bench separates four layers: case sealing, candidate-visible execution, evaluator-only gold, and scoring. The candidate receives a frozen control/candidate environment and a minimal opaque view. The evaluator retains labels, historical discussion, and post-cutoff evidence outside that environment.

The decisive experiment compares three immutable lanes on the same 25 cases. No model is tuned after labels are admitted. A result is useful only when the experiment distinguishes control from candidate and the final claim remains supported by the ledger. An unresolved or blocked case stays unresolved or blocked.

The benchmark is intentionally small. Its purpose is to falsify unsafe reasoning strategies and test reproducibility, not to estimate real-world population accuracy.
