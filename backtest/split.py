"""Train / out-of-sample split and walk-forward windows (dates in America/New_York)."""
from __future__ import annotations

import pandas as pd

import config
from data.base import to_ts


def in_period(index: pd.DatetimeIndex, start, end) -> pd.Series:
    """True for timestamps on dates start..end (inclusive)."""
    d = index.normalize()
    return pd.Series((d >= to_ts(start)) & (d <= to_ts(end)), index=index)


def is_train(index: pd.DatetimeIndex) -> pd.Series:
    return in_period(index, config.TRAIN_START, config.TRAIN_END)


def is_oos(index: pd.DatetimeIndex) -> pd.Series:
    return in_period(index, config.OOS_START, config.OOS_END)


def walk_forward_windows(start, end, train_months: int = 3, test_months: int = 1
                         ) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Rolling (train_start, train_end, test_start, test_end); test periods do not overlap."""
    start, end = to_ts(start), to_ts(end)
    out = []
    t0 = start
    while True:
        train_end = t0 + pd.DateOffset(months=train_months) - pd.Timedelta(days=1)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + pd.DateOffset(months=test_months) - pd.Timedelta(days=1)
        if test_end > end:
            break
        out.append((t0, train_end, test_start, test_end))
        t0 = t0 + pd.DateOffset(months=test_months)
    return out
