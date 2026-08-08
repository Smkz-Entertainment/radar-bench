# ADR 0002: separate inference and gold snapshots

Inference packets contain only evidence explicitly attested as available no
later than Tcut. Curator resolution records are written under `gold/` and are
never traversed by inference loaders. Leakage checks scan both identifiers and
URLs so directory naming alone is not a control.

