# Status

Status is partial until the complete local suite, package smoke test, and
public-source curation gates have run. The seed records are deliberately
status-marked and do not claim that manifest links alone constitute verified
gold evidence.

## Decisions

- Runtime dependencies are empty in v0.1 so schema, temporal, and safety checks
  remain runnable offline.
- The standard-library HTTP client is read-only and rejects non-GitHub hosts.
- Gold evidence is stored separately and inference loaders refuse gold paths.
- Unsupported attributions abstain instead of guessing an owner.

## Known limitations

- Public GitHub collection depends on network/rate-limit availability.
- The seed manifest is a curation queue; only the worked OpenBLAS record is a
  complete reference case in this local foundation.
- The custom validator deliberately implements the repository's JSON Schema
  subset; external schema-hosting and production-scale corpus expansion remain
  future work.

