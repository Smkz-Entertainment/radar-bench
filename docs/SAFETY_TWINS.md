# Safety twins

The twenty safety twins are executable controls for baseline-already-broken behavior, dead resources, missing artifacts, resolver confounding, flakiness, and platform confounding. Their evaluator labels are in `corpus/v0.7/safety-twins/evaluator-labels.json`, outside the candidate-visible runtime tree.

Runtime views expose only neutral plausible-component metadata. The opacity audit scans candidate-visible files for gold, historical, post-cutoff, incident, and repository-specific labels before execution.
