"""Reproduce the pandas #66085 duplicated ISO8601 parsing crash."""

from datetime import datetime, timedelta, timezone

import pandas as pd


start = datetime(2024, 1, 1, tzinfo=timezone.utc)
values = [(start + timedelta(minutes=index)).isoformat() for index in range(50)] * 60
pd.to_datetime(pd.Series(values))
