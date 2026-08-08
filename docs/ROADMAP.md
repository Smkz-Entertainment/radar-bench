# Roadmap

# Roadmap

v0.1 is frozen. v0.2 is Attribution Validation and has one purpose: determine
whether Radar meets the attribution and abstention gates on an independently
derived, temporally clean, adversarial corpus.

The v0.2 sequence is:

1. Fill the 100-slot admission plan from public evidence; do not let the
   evaluated agent create gold labels.
2. Overweight negative controls and admit only cases with post-cutoff causal
   and resolution/post-fix evidence.
3. Measure attribution precision/recall, abstention precision/recall,
   first-bad localization, experiments requested/useful, calibration, cost,
   and unsupported confident claims.
4. Run deterministic, local-model, and Codex lanes on the exact same hidden
   cases. Codex must demonstrate measurable lift without adding false
   high-confidence upstream accusations.
5. Require zero false high-confidence upstream accusations in the first
   roughly 100-case evaluation set before product work begins.

Only after v0.2 passes should shadow-mode ingestion, a public corpus/dashboard,
or other user-facing Radar product work be considered. No GitHub bot or
maintainer-contact integration is planned.
