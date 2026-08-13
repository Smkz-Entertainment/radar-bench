# Production reference inventory

The v1.1.1 hygiene review inspected every production Python module and searched
imports, calls, scripts, tests, documentation, and package resources.

| Area | Decision | Reason |
| --- | --- | --- |
| `radar_bench.v12_executor` and `v1_2` | KEEP | Current decisive-v1.2 evaluator-owned executor and protocol contract. |
| `radar_bench.artifacts`, `historical_runtime`, `execution.canonical`, `release` | KEEP | Current acquisition, historical reconstruction, v1.1 canonical regression, and result validation paths. |
| `radar_bench.execution.v07` | KEEP / historical runtime namespace | Required by decisive-v1.1 and frozen v0.4/v0.5 reproduction; `preparation_audit` and `evaluate_pilot` are historical helpers, not new product behavior. |
| `radar_bench.providers` | KEEP | Small provider-neutral subprocess API with bounded execution and security tests; it remains an extension boundary even though the canonical harness does not select a provider dynamically. |
| `radar_bench.investigation.v01` | KEEP / historical lane | Implements the frozen investigator used by the canonical reference and must remain reproducible. |
| `scripts/run_protocol_smoke.py`, `run_historical_reconstruction.py`, `run_candidate_only_reference.py` | KEEP | Current release and solvability receipts. |
| `scripts/audit_metadata_only.py`, `audit_v12_leakage.py`, `check_coverage.py`, `check_public_state.py`, `check_links.py`, `audit_release_assets.py` | KEEP | Current contract, security, or release gates. |
| `scripts/verify_v12.py` | KEEP | Current indexed evidence generator; its outputs are limited to evidence summaries. |
| `scripts/verify_release.py` | KEEP / documented historical verifier | Preserves v1.0.1 release verification and is covered by regression tests; it is not the v1.1.1 release workflow. |

No production module was removed. The review found no safe removal that would
preserve the frozen reproduction contract while reducing meaningful maintenance
surface; deleting the v0.7 or provider paths would trade a cosmetic cleanup for
loss of reproducibility or a supported subprocess boundary.
