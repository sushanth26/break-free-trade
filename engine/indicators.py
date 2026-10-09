"""Indicators shared by the engine modules. Pure functions, no I/O.

All values at bar t use only bars <= t. Formulas follow TradingView:
ATR = Wilder RMA (SMA-seeded) of true range; EMA seeded with the first value.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


def session_dates(index: pd.DatetimeIndex) -> np.ndarray:
    return index.normalize().values


def true_range(bars: pd.DataFrame, ignore_gaps: bool = False) -> pd.Series:
    """True range. With ``ignore_gaps`` the first bar of each day uses high - low,
    so overnight gaps do not inflate intraday ATR."""
    prev_close = bars["close"].shift(1)
    if ignore_gaps:
        new_day = pd.Series(session_dates(bars.index), index=bars.index).diff() != pd.Timedelta(0)
        prev_close = prev_close.mask(new_day)
    hl = bars["high"] - bars["low"]
    hc = (bars["high"] - prev_close).abs()
    lc = (bars["low"] - prev_close).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1, skipna=True)


def rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder moving average, seeded with the SMA of the first ``period`` values (ta.rma)."""
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) >= period:
        out[period - 1] = values[:period].mean()
        for i in range(period, len(values)):
            out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return pd.Series(out, index=series.index)


def atr(bars: pd.DataFrame, period: int = config.ATR_PERIOD, ignore_gaps: bool = False) -> pd.Series:
    return rma(true_range(bars, ignore_gaps), period)


def ema(series: pd.Series, period: int) -> pd.Series:
    """TradingView ta.ema: alpha = 2/(n+1), seeded with the first value."""
    return series.ewm(span=period, adjust=False).mean()


def vwap(bars: pd.DataFrame) -> pd.Series:
    """Session-anchored VWAP on hlc3, reset each calendar day."""
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3
    day = session_dates(bars.index)
    pv = (tp * bars["volume"]).groupby(day).cumsum()
    vol = bars["volume"].groupby(day).cumsum()
    return pv / vol.where(vol > 0)


def ema_clouds(close: pd.Series) -> pd.DataFrame:
    """Ripster EMA clouds: fast 5/12 and slow 34/50. bull = short EMA above long EMA."""
    f1, f2 = config.EMA_CLOUD_FAST
    s1, s2 = config.EMA_CLOUD_SLOW
    out = pd.DataFrame({
        "fast_a": ema(close, f1), "fast_b": ema(close, f2),
        "slow_a": ema(close, s1), "slow_b": ema(close, s2),
    })
    out["fast_bull"] = out["fast_a"] > out["fast_b"]
    out["slow_bull"] = out["slow_a"] > out["slow_b"]
    return out


def time_slot(index: pd.DatetimeIndex) -> pd.Index:
    return pd.Index(index.strftime("%H:%M"))


def rvol_baseline(bars: pd.DataFrame, lookback_days: int = config.RVOL_LOOKBACK_DAYS) -> pd.Series:
    """Average volume per time-of-day slot over the prior ``lookback_days`` sessions
    (the current day is excluded, so no lookahead)."""
    df = pd.DataFrame({"vol": bars["volume"].to_numpy(), "slot": time_slot(bars.index),
                       "day": session_dates(bars.index)}, index=bars.index)
    wide = df.pivot_table(index="day", columns="slot", values="vol", aggfunc="sum")
    base = wide.shift(1).rolling(lookback_days, min_periods=1).mean()
    stacked = base.stack()
    keys = list(zip(df["day"], df["slot"]))
    return pd.Series([stacked.get(k, np.nan) for k in keys], index=bars.index)


def rvol(bars: pd.DataFrame, lookback_days: int = config.RVOL_LOOKBACK_DAYS) -> pd.Series:
    """Volume relative to the same time slot on prior days."""
    return bars["volume"] / rvol_baseline(bars, lookback_days)


def opening_range(bars: pd.DataFrame, minutes: int = config.OPENING_RANGE_MINUTES,
                  bar_minutes: int = 5) -> pd.DataFrame:
    """Opening-range high/low per day, NaN until the range has closed."""
    open_t = pd.Timestamp(config.REGULAR_OPEN).time()
    start = bars.index.normalize() + pd.Timedelta(hours=open_t.hour, minutes=open_t.minute)
    in_or = (bars.index >= start) & (bars.index < start + pd.Timedelta(minutes=minutes))
    day = session_dates(bars.index)
    hi = bars["high"].where(in_or).groupby(day).transform("max")
    lo = bars["low"].where(in_or).groupby(day).transform("min")
    ready = bars.index + pd.Timedelta(minutes=bar_minutes) >= start + pd.Timedelta(minutes=minutes)
    return pd.DataFrame({"or_high": hi.where(ready), "or_low": lo.where(ready)}, index=bars.index)
