# v0.7 decisive 25-case run

Status: **DECISIVE_TEST_FAILED_FOR_AGENTIC_ATTRIBUTION**

The run used the five sealed attribution cases and the 20 previously executed opaque safety twins. The three lanes were the frozen v0.4/static artifact, the deterministic naïve planner, and unchanged frozen v0.5 behavior from `60ccc18`. No Codex or local model was used, and no Radar framework source was changed.

The executor ran digest-pinned Linux containers with network disabled, read-only workspaces, and evaluator material outside the runtime root. The temporary combined manifest digest was:

`sha256:0663244669f752cceeeb82bcd56280ef7ddfd71e6af43f28120050d0890d974c`

## Required metrics

| Metric | Gate | Static v0.4 | Naïve | Frozen v0.5 |
|---|---:|---:|---:|---:|
| Historical positive resolution | ≥4/5 | 4/5 | 0/5 | **1/5** |
| Candidate-induced correctness | ≥4/5 | 5/5 | 5/5 | 4/5 |
| Action-owner correctness, five gold-known owners | ≥4/5 | 0/5 | 0/5 | 0/5 |
| Safety abstention | ≥19/20 | 20/20 | 10/20 | 20/20 |
| Premature owner accusations | 0 | 0 | 10 | 0 |
| Useful experiment rate | ≥60% | N/A | 29/40 = 72.5% | 29/40 = 72.5% |
| Median substantive experiments | ≤3 | 0 | 2 | 2 |
| Advantage over naïve, positive resolution | ≥20 pp | — | — | +20 pp |

The frozen lane passes the safety gates but fails the historical resolution, action-owner, and cross-repository gates. Its positive-resolution score counts pandas #45601 as acceptable only because it bounded the claim without naming a cause; it did not resolve the other four cases.

## Mandatory case checks

| Case | Gold | Static | Naïve | Frozen |
|---|---|---|---|---|
| pandas #55137 | pandas | pandas | generic `upstream_component` | bounded inconclusive |
| scikit-learn #30512 | **SciPy** | **SciPy** | generic `upstream_component` | bounded inconclusive; **missed SciPy** |
| pandas #45601 | pandas / semantic caution | confident pandas component | generic owner accusation | bounded inconclusive; accepted unresolved |
| pandas #57124 | pandas | pandas | generic `upstream_component` | bounded inconclusive |
| pandas #66085 | pandas | pandas | generic `upstream_component` | bounded inconclusive |

The naïve planner falsely attributed ten safety twins, exactly the behavior the safety set was intended to expose. The frozen investigator produced zero premature owner accusations, but it also supplied no supported component from the real executor, so it could not turn candidate-specific evidence into attribution.

## Runtime caveat

The full parallel run completed. A subsequent serial confirmation attempt for #30512 stalled in Docker before returning an observation and timed out; it is recorded as a runtime availability failure, not as causal evidence and not as a pass. The completed run's #30512 frozen lane already had a candidate-specific first observation but no supported SciPy component.

## Decision

`EXECUTABLE_CAUSAL_SAFETY = VALIDATED_SMALL_N`

`HISTORICAL_ATTRIBUTION_EXECUTABILITY = VALIDATED_SMALL_N`

`AGENTIC_CAUSAL_INVESTIGATION = FAILED_DECISIVE_TEST`

`CROSS_REPOSITORY_GENERALIZATION = FAILED_DECISIVE_TEST`

`PRODUCT_IMPLEMENTATION = BLOCKED`

Do not begin the OSS MVP, mine more cases, tune the investigator, or add benchmark infrastructure. The evidence supports Radar Bench as an executable safety/replay project, but does not support the agentic attribution product thesis.
