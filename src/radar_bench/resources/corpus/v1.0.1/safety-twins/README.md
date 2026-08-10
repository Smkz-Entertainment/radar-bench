# v0.7 executable causal-safety twins

This is a separate executable lane from the historical attribution seals.
The twins are deliberately constructed counterfactual incidents used to test
safe abstention when a candidate-only failure is not sufficient evidence of
causation.

The runtime manifest contains only opaque profiles, generic observations, and
local read-only workspaces.  Fault-family labels are evaluator-only and are
kept in `evaluator-labels.json`; that file is not referenced by the runtime
manifest and is never mounted into a container.

The lane exercises the unchanged v0.7 executor and the frozen investigator at
commit `60ccc18`.  It is not promoted into
`corpus/v1.0.1/executable-subset.json`, and it does not change the v0.7
preparation gate.

Run the lane from the repository root after Docker is available:

```powershell
$env:PYTHONPATH = 'src'
python -c "import json; from pathlib import Path; from radar_bench.execution.v07 import HermeticExecutor, adapt_frozen_request; from radar_bench.investigation.v01 import HeuristicInvestigator; r=Path('.'); m=json.loads((r/'corpus/v1.0.1/safety-twins/runtime-manifest.json').read_text()); e=HermeticExecutor(m, root=r); out=[]; [out.append(HeuristicInvestigator(root=r).run({**json.loads((r/c['candidate_view']).read_text()),'episode_id':'RADAR-V05-E-'+c['case_id'].rsplit('-',1)[-1]}, lambda q: e.execute(adapt_frozen_request({**q,'episode_id':'RADAR-V07-'+q['episode_id'].rsplit('-',1)[-1]})))) for c in m['cases']]; print(json.dumps({'cases':len(out),'states':{s:sum(1 for x in out if x['terminal']['state']==s) for s in sorted({x['terminal']['state'] for x in out})}}, indent=2))"
```

The expected first run is twenty completed executions with all investigator
terminals abstaining (`BOUNDED_INCONCLUSIVE`). That is an execution result,
not evidence that the causal-investigation hypothesis has passed.
