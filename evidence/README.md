# Public evidence index

This directory contains concise, independently useful scientific and provenance
evidence. Raw CI logs, scanner output, wheelhouses, and temporary execution
directories belong in Actions artifacts or release assets, not the default tree.

## Index

- [decisive-v1.1](decisive-v1.1/README.md) - preserved historical reference,
  frozen baselines, canonical result, artifact integrity, and reproduction
  summaries;
- [decisive-v1.2](decisive-v1.2/README.md) - current candidate protocol,
  evaluator separation, solvability, isolation, artifact, package, security,
  and release evidence.

Evidence names are stable within a suite directory. A changed benchmark case,
label, scoring rule, or runtime isolation contract requires a new suite identity;
this patch changes none of those.
