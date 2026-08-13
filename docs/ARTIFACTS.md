# Artifact inventory

The default branch stores manifests, small indexed evidence, schemas, and
candidate-visible runtime fixtures. It does not store historical wheel bytes,
release wheel/sdist binaries, raw CI logs, or scanner logs.

## Public inputs

- `src/radar_bench/resources/candidate/` contains candidate-visible v1.2
  contract data;
- `src/radar_bench/resources/corpus/v1.0.1/.../reproducers/` and safety runtime
  fixtures are the intentionally shipped public runtime inputs;
- `corpus/v1.0.1/` and `corpus/v1.1.0/` contain manifests and suite contracts;
- the evaluator bundle is released separately as
  `radar-bench-decisive-v1.2-evaluator.json` and is excluded from wheel/sdist;
- historical wheelhouses are acquired into an external artifact root and checked
  by `radar-bench artifacts verify`.

## Indexed evidence

`evidence/README.md` indexes the retained scientific and provenance records.
Evidence is concise enough to review in the repository; raw CI and scanner
output belongs in GitHub Actions artifacts or release assets.
