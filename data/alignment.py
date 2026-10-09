"""Alpaca vs Webull 5m bar alignment check (Day 1 gate).

On the completed days both sources cover, bars must share the bar-start
timestamp convention and session split. Price differences (close, high,
low) are measured in units of the bar's 5m ATR, like every other distance:
the typical bar must agree to ALIGN_PRICE_P95_ATR (the engine's 0.1 ATR
precision) and no bar may differ by more than ALIGN_PRICE_MAX_ATR. Volume
must agree within ALIGN_VOLUME_TOL_PCT on ALIGN_VOLUME_MIN_SHARE of bars;
the closing-auction bar is skipped because Webull folds the 16:00 cross into
it and Alpaca does not. The backtest is blocked until this passes.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import config
from data.base import session_mask, timeframe_delta
from engine.indicators import atr

PRICE_COLS = ("close", "high", "low")


@dataclass
class AlignmentResult:
    symbol: str
    session: str
    matched: int
    only_a: int
    only_b: int
    best_shift_bars: int     # timestamp offset (in bars) that matches best; must be 0
    price_p95_atr: float     # worst of the close/high/low 95th-percentile |A - W|, in 5m ATR
    price_max_atr: float     # worst |A - W| over close/high/low, in 5m ATR
    price_fail: int          # bars with any price diff above ALIGN_PRICE_P95_ATR
    volume_within: float     # share of bars (auction bar excluded) with volume within tolerance
    median_volume_diff_pct: float

    @property
    def passed(self) -> bool:
        return (self.matched > 0 and self.best_shift_bars == 0 and self.only_a == 0 and self.only_b == 0
                and self.price_p95_atr <= config.ALIGN_PRICE_P95_ATR
                and self.price_max_atr <= config.ALIGN_PRICE_MAX_ATR
                and self.volume_within >= config.ALIGN_VOLUME_MIN_SHARE)


def _close_match_rate(a: pd.DataFrame, b: pd.DataFrame) -> float:
    common = a.index.intersection(b.index)
    if len(common) == 0:
        return 0.0
    diff = (a.loc[common, "close"] - b.loc[common, "close"]).abs() / a.loc[common, "close"] * 100
    return float((diff <= config.ALIGN_SHIFT_CLOSE_PCT).mean())


def detect_shift(a: pd.DataFrame, b: pd.DataFrame, tf: str = "5m", max_shift: int = 2) -> int:
    """Bars by which ``b`` timestamps are offset from ``a`` (0 = same convention)."""
    step = timeframe_delta(tf)
    rates = {k: _close_match_rate(a, b.set_axis(b.index - k * step)) for k in range(-max_shift, max_shift + 1)}
    return max(rates, key=lambda k: (rates[k], -abs(k)))


def _overlap(a: pd.DataFrame, b: pd.DataFrame, session: str, before=None
             ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bars of both sources on the days both cover (dates < ``before`` only), within ``session``."""
    days = set(a.index.date) & set(b.index.date)
    if before is not None:
        days = {d for d in days if d < pd.Timestamp(before).date()}
    a = a[[d in days for d in a.index.date]]
    b = b[[d in days for d in b.index.date]]
    return a[session_mask(a.index, session).values], b[session_mask(b.index, session).values]


def bar_diffs(a: pd.DataFrame, b: pd.DataFrame, session: str = "regular", before=None) -> pd.DataFrame:
    """Per matched bar: price diffs in 5m ATR (ATR from ``a``'s full history) and volume diff %."""
    atr_a = atr(a)
    a, b = _overlap(a, b, session, before)
    common = a.index.intersection(b.index)
    ca, cb, unit = a.loc[common], b.loc[common], atr_a.reindex(common)
    out = pd.DataFrame(index=common)
    for c in PRICE_COLS:
        out[f"{c}_atr"] = (ca[c] - cb[c]).abs() / unit
    out["price_atr"] = out[[f"{c}_atr" for c in PRICE_COLS]].max(axis=1)
    out["close_a"], out["close_b"] = ca["close"], cb["close"]
    out["vol_a"], out["vol_b"] = ca["volume"], cb["volume"]
    out["vol_pct"] = (ca["volume"] - cb["volume"]).abs() / ca["volume"].where(ca["volume"] > 0) * 100
    out["auction"] = common.strftime("%H:%M").isin(config.ALIGN_SKIP_VOLUME_SLOTS)
    return out


def mismatches(a: pd.DataFrame, b: pd.DataFrame, session: str = "regular", before=None) -> pd.DataFrame:
    """Bars over the price or volume tolerance, worst price difference first."""
    d = bar_diffs(a, b, session, before)
    bad = (d["price_atr"] > config.ALIGN_PRICE_P95_ATR) | (
        ~d["auction"] & (d["vol_pct"] > config.ALIGN_VOLUME_TOL_PCT))
    return d[bad].sort_values(["price_atr", "vol_pct"], ascending=False)


def compare_bars(a: pd.DataFrame, b: pd.DataFrame, symbol: str, tf: str = "5m",
                 session: str = "regular", before=None) -> AlignmentResult:
    """Compare provider ``a`` (Alpaca) with ``b`` (Webull) on their overlapping days.

    ``before``: only dates before this one (pass today so a forming session is skipped).
    """
    d = bar_diffs(a, b, session, before)
    oa, ob = _overlap(a, b, session, before)
    vol = d.loc[~d["auction"], "vol_pct"].dropna()
    cols = [d[f"{c}_atr"].dropna() for c in PRICE_COLS]
    nan = float("nan")
    return AlignmentResult(
        symbol=symbol, session=session, matched=len(d),
        only_a=len(oa.index.difference(ob.index)), only_b=len(ob.index.difference(oa.index)),
        best_shift_bars=detect_shift(oa, ob, tf),
        price_p95_atr=max(float(c.quantile(0.95)) for c in cols) if len(d) else nan,
        price_max_atr=max(float(c.max()) for c in cols) if len(d) else nan,
        price_fail=int((d["price_atr"] > config.ALIGN_PRICE_P95_ATR).sum()),
        volume_within=float((vol <= config.ALIGN_VOLUME_TOL_PCT).mean()) if len(vol) else nan,
        median_volume_diff_pct=float(vol.median()) if len(vol) else nan,
    )
