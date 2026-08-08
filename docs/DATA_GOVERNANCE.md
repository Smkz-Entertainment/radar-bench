# Data governance

Radar stores public-source identifiers, digests, timestamps, structured
metadata, and short minimized excerpts. It avoids bulk redistribution of issue
or CI-log bodies and retains source links for verification. Authorization
headers, cookies, signed URLs, and secrets are never persisted.

Cases carry visibility, redaction, provenance, lifecycle, correction, and
retraction state. A retracted case cannot remain benchmark gold without an
explicit superseding label. Corrections are append-only and auditable. Any
future private-data mode requires separate access controls, retention rules,
legal review, and aggregation checks before implementation.

