# Benchmark integrity

Integrity requires distinct runtime and evaluator trees, validated hashes, no future evidence, no network, independent control/candidate environments, and fail-closed handling of unavailable inputs. The v0.6 replay oracle violated the practical gold boundary and was rejected. v1 preserves that negative result and audits the executable safety set instead of reusing replay outputs.
