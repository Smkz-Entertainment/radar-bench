# decisive-v1 correction record

This file records a correction to the sealed A03 reproducer without rewriting
the original decisive-run evidence.

## A03: pandas #45601

The first local runtime attempt used a one-row `Series` fixture:

```python
pd.Series([1], dtype="Int64").replace({pd.NA: None})
```

That fixture was not the upstream reproducer. It failed in the control
environment, so it could not establish the required control-pass/candidate-fail
behavior.

The current `decisive-v1` recipe uses the upstream issue's two-row nullable
`DataFrame` reproducer instead:

```python
frame = pd.DataFrame({"value": [42, None]}).astype({"value": "Int64"})
expected = {"value": {0: 42, 1: None}}
if frame.replace({pd.NA: None}).to_dict() != expected:
    raise AssertionError("pd.NA was not replaced with None")
```

Source: [pandas issue #45601](https://github.com/pandas-dev/pandas/issues/45601).

## Evidence boundary

- The original `corpus/v0.7/decisive-run/result.json` and
  `corpus/v0.7/decisive-run/REPORT.md` are preserved unchanged. They are
  historical evidence from the earlier decisive run, not regenerated runtime
  evidence.
- The corrected recipe is part of the existing `decisive-v1` identity because
  the intended case semantics and expected behavior did not change: control
  exits `0`, candidate exits `1`.
- The corrected fixture was rerun in the sealed control and candidate
  environments and produced `0/1`. That result belongs to the runtime
  reconstruction evidence, not to the earlier decisive-run record.
- No evaluator label, owner, post-cutoff discussion, or canonical reference
  was made visible to the candidate while the corrected reproducer ran.

If a future correction changes the case meaning, expected exit behavior, or
candidate-visible interface, it must receive a new immutable suite revision
instead of modifying `decisive-v1` in place.
