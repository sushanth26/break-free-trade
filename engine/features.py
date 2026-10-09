"""Per-bar indicator table shared by every engine module.

``compute_features`` is causal: the row for bar t uses only bars <= t, so it
can be computed once over history (backtest) or over a rolling window (live)
with identical results. A row is usable at the bar's close.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from data.base import bar_close_times, session_mask, timeframe_delta
from engine import indicators as ind


def _ffill_by_close(src: pd.Series, src_close: pd.DatetimeIndex, target: pd.DataFrame,
                    target_close: pd.DatetimeIndex) -> pd.Series:
    """Value of ``src`` from its latest bar closed by each target bar's close."""
    left = pd.DataFrame({"t": target_close}).reset_index(drop=True)
    right = pd.DataFrame({"t": src_close, "v": src.to_numpy()}).dropna().reset_index(drop=True)
    if right.empty:
        return pd.Series(np.nan, index=target.index)
    out = pd.merge_asof(left, right, on="t", direction="backward")
    return pd.Series(out["v"].to_numpy(), index=target.index)


class Row(dict):
    """A feature row as a plain dict (fast lookups) that keeps its bar time in ``.name``."""
    __slots__ = ("name",)

    def __init__(self, data, name):
        super().__init__(data)
        self.name = name


def feature_rows(feats: pd.DataFrame) -> list[Row]:
    """All rows of a feature table as Row dicts, in order."""
    cols = list(feats.columns)
    return [Row(zip(cols, vals), t) for t, vals in zip(feats.index, feats.itertuples(index=False, name=None))]


def compute_features(bars: pd.DataFrame, daily: pd.DataFrame | None = None) -> pd.DataFrame:
    """Indicators for 5m bars (regular + extended hours if present)."""
    f = pd.DataFrame(index=bars.index)
    close5 = bars.index + timeframe_delta("5m")
    reg = session_mask(bars.index, "regular").to_numpy()
    f["regular"] = reg
    f["premarket"] = session_mask(bars.index, "premarket").to_numpy()
    for c in ("open", "high", "low", "close", "volume"):
        f[c] = bars[c]

    reg_bars = bars[reg]
    atr = ind.atr(reg_bars, config.ATR_PERIOD, ignore_gaps=True)
    f["atr"] = atr.reindex(bars.index).ffill()

    f["vwap"] = ind.vwap(bars)
    for n in config.EMA_CLOUD_FAST + config.EMA_CLOUD_SLOW:
        f[f"ema{n}"] = ind.ema(bars["close"], n)
    f["fast_bull"] = f[f"ema{config.EMA_CLOUD_FAST[0]}"] > f[f"ema{config.EMA_CLOUD_FAST[1]}"]
    f["slow_bull"] = f[f"ema{config.EMA_CLOUD_SLOW[0]}"] > f[f"ema{config.EMA_CLOUD_SLOW[1]}"]
    f["cloud_fast_lo"] = f[[f"ema{n}" for n in config.EMA_CLOUD_FAST]].min(axis=1)
    f["cloud_fast_hi"] = f[[f"ema{n}" for n in config.EMA_CLOUD_FAST]].max(axis=1)
    f["cloud_slow_lo"] = f[[f"ema{n}" for n in config.EMA_CLOUD_SLOW]].min(axis=1)
    f["cloud_slow_hi"] = f[[f"ema{n}" for n in config.EMA_CLOUD_SLOW]].max(axis=1)

    # 10m clouds from closed 10m bars
    b10 = bars.resample("10min", origin="start_day", offset="9h30min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["open"])
    c10 = b10.index + pd.Timedelta("10min")
    a, b = (ind.ema(b10["close"], n) for n in config.EMA_CLOUD_SLOW)
    fa, fb = (ind.ema(b10["close"], n) for n in config.EMA_CLOUD_FAST)
    f["slow_bull_10m"] = _ffill_by_close((a > b).astype(float), c10, f, close5) > 0.5
    f["fast_bull_10m"] = _ffill_by_close((fa > fb).astype(float), c10, f, close5) > 0.5

    f["rvol"] = ind.rvol(bars)
    f["vol_avg"] = bars["volume"].shift(1).rolling(config.VOLUME_AVG_BARS, min_periods=1).mean()
    orng = ind.opening_range(bars)
    f["or_high"], f["or_low"] = orng["or_high"], orng["or_low"]

    day = bars.index.normalize()
    reg_close = bars["close"].where(reg)
    # prior regular-session close: last regular close of the previous trading day
    closes = reg_close.groupby(day).last().dropna()
    f["prev_close"] = pd.Series(day, index=bars.index).map(closes.shift(1))
    f["day_open"] = bars["open"].where(reg).groupby(day).transform("first")
    f.loc[~reg & (bars.index.strftime("%H:%M") < config.REGULAR_OPEN), "day_open"] = np.nan
    f["prev_high"] = pd.Series(day, index=bars.index).map(bars["high"].where(reg).groupby(day).max().shift(1))
    f["prev_low"] = pd.Series(day, index=bars.index).map(bars["low"].where(reg).groupby(day).min().shift(1))
    f["day_high"] = bars["high"].groupby(day).cummax()
    f["day_low"] = bars["low"].groupby(day).cummin()

    if daily is not None and len(daily):
        datr = ind.atr(daily, config.DAILY_ATR_PERIOD)
        f["daily_atr"] = _ffill_by_close(datr, bar_close_times(daily, "D"), f, close5)
    else:
        f["daily_atr"] = np.nan
    return f
