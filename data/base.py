"""Standard bar schema, provider interface and timeframe helpers.

Every provider returns bars in the standard schema: pandas DataFrame,
tz-aware index in America/New_York holding the bar START time, float
columns open/high/low/close/volume, sorted, de-duplicated.

A bar is only usable once it has closed, at ``start + timeframe``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

import config

COLUMNS = ["open", "high", "low", "close", "volume"]

_FREQ = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "D": "1D"}


def timeframe_delta(tf: str) -> pd.Timedelta:
    """Bar length; a daily bar is treated as ending at the regular close."""
    if tf not in _FREQ:
        raise ValueError(f"unknown timeframe {tf!r}")
    return pd.Timedelta(_FREQ[tf])


def to_ts(value, tz: str = config.TZ) -> pd.Timestamp:
    """Any date-like value as a tz-aware Timestamp (naive values are taken as local)."""
    ts = pd.Timestamp(value)
    return ts.tz_localize(tz) if ts.tzinfo is None else ts.tz_convert(tz)


def clip(bars: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    """Bars with start <= index < end."""
    if start is not None:
        bars = bars[bars.index >= to_ts(start)]
    if end is not None:
        bars = bars[bars.index < to_ts(end)]
    return bars


def normalize_bars(df: pd.DataFrame, tz: str = config.TZ) -> pd.DataFrame:
    """Coerce any provider output into the standard bar schema."""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([], tz=tz), dtype=float)
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    missing = [c for c in COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(f"bars missing columns {missing}")
    idx = pd.DatetimeIndex(pd.to_datetime(out.index))
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    out.index = idx.tz_convert(tz)
    out.index.name = "time"
    out = out[COLUMNS].astype(float)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def session_mask(index: pd.DatetimeIndex, session: str = "regular") -> pd.Series:
    """True for bars inside the session ('regular', 'premarket', 'afterhours', 'extended')."""
    t = index.strftime("%H:%M")
    reg = (t >= config.REGULAR_OPEN) & (t < config.REGULAR_CLOSE)
    pre = (t >= config.PREMARKET_START) & (t < config.REGULAR_OPEN)
    post = (t >= config.REGULAR_CLOSE) & (t < config.AFTERHOURS_END)
    masks = {"regular": reg, "premarket": pre, "afterhours": post, "extended": pre | reg | post}
    return pd.Series(masks[session], index=index)


def regular_hours(bars: pd.DataFrame) -> pd.DataFrame:
    return bars[session_mask(bars.index, "regular").values]


def resample(bars: pd.DataFrame, tf: str, regular_only: bool = True) -> pd.DataFrame:
    """Build higher-timeframe bars from lower ones.

    Intraday bars are anchored at the 09:30 open (TradingView convention), so
    a 1h bar runs 09:30-10:30. Index = bar start, like every other bar.
    """
    src = regular_hours(bars) if regular_only else bars
    if src.empty:
        return src.copy()
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if tf == "D":
        out = src.groupby(src.index.normalize()).agg(agg)
        out.index = pd.DatetimeIndex(out.index)
    else:
        out = src.resample(_FREQ[tf], origin="start_day", offset="9h30min",
                           label="left", closed="left").agg(agg)
    return out.dropna(subset=["open"])


def bar_close_times(bars: pd.DataFrame, tf: str) -> pd.DatetimeIndex:
    """Time each bar becomes available (its close)."""
    if tf == "D":
        h, m = map(int, config.REGULAR_CLOSE.split(":"))
        return bars.index.normalize() + pd.Timedelta(hours=h, minutes=m)
    return bars.index + timeframe_delta(tf)


def closed_bars(bars: pd.DataFrame, tf: str, now: pd.Timestamp) -> pd.DataFrame:
    """Only the bars of timeframe ``tf`` that have closed by ``now`` (no lookahead).

    The final resampled bar of a session can be shorter than ``tf`` (e.g. the
    15:30 1h bar); it is still only released at start + tf, the conservative choice.
    """
    closes = bar_close_times(bars, tf)
    return bars[closes <= now]


class BarProvider(ABC):
    """Interface every data source implements."""

    name: str = "base"

    @abstractmethod
    def get_bars(self, symbol: str, tf: str, start: pd.Timestamp | None = None,
                 end: pd.Timestamp | None = None) -> pd.DataFrame:
        """Return bars in the standard schema."""
