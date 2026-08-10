"""Reproduce the pandas #45601 nullable replacement regression."""

import pandas as pd


frame = pd.DataFrame({"value": [42, None]}).astype({"value": "Int64"})
expected = {"value": {0: 42, 1: None}}
if frame.replace({pd.NA: None}).to_dict() != expected:
    raise AssertionError("pd.NA was not replaced with None")
