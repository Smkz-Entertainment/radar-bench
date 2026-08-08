# Architecture

The data flow is:

`public GitHub URL -> allowlisted client -> CAS object + SQLite metadata ->
curated RegressionCase -> T0/Tcut input snapshot + Tgold gold snapshot ->
provider prediction -> strict evidence-aware scorer -> exploratory gates`.

Trust boundaries are explicit. Remote payloads and repository text are data,
never commands. Provider processes receive an immutable input packet through
JSON stdin and return JSON stdout. The inference loader refuses paths beneath
`gold`. Experiment plans are typed and dry-run only in v0.1.

The standard library is the portable core. HTTP, storage, normalization,
baseline, evaluation, and providers are narrow modules with extension points;
no API-specific model dependency is required.

