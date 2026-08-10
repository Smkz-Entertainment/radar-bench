"""Reproduce the pandas #57124 DataFrame.update warning regression."""

from datetime import datetime
import warnings

import pandas as pd


columns = ["Open", "High", "Low", "Close", "Volume"]
df = pd.DataFrame(
    [[451.5, 458.0, 449.0, 455.5, 1239498]],
    columns=columns,
    index=[datetime(2024, 1, 29)],
)
df2 = pd.DataFrame(
    [
        [450.5, 457.5, 450.0, 453.5, 1385875],
        [451.5, 458.0, 449.0, 455.5, 1284000],
    ],
    columns=columns,
    index=[datetime(2024, 1, 26), datetime(2024, 1, 29)],
)
with warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always", FutureWarning)
    df2.update(df)
if any(item.category is FutureWarning for item in captured):
    raise SystemExit(1)
