# Radar v0.2 Attribution Validation Corpus

This directory is an admission plan, not a gold benchmark. It contains 100
planned slots across the adversarial distribution proposed for v0.2. Every
record starts as `planned` with no source URL, independent evidence, or gold
label. Planned records are never counted as evaluation gold.

Admission requires later public evidence outside the inference cutoff: causal
support, a resolution or post-fix signal, temporal metadata, and an independent
review record. The evaluated provider is prohibited from creating its own gold
label. Records that do not meet the protocol remain `candidate`, `blocked`, or
`rejected`.

The negative-control plan deliberately includes dead URLs, outages, missing
wheels, resolver drift, worker crashes, flakiness, baseline failures,
platform infrastructure, expired certificates, fixture disappearance, and
incorrect xfails. This is research planning evidence, not a claim that those
cases have already been collected.
