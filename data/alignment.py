"""Alpaca vs Webull 5m bar alignment check (Day 1 gate).

On the days both sources cover, bars must share the bar-start timestamp
convention and session split, with closes within ALIGN_CLOSE_TOL_PCT and
volume within ALIGN_VOLUME_TOL_PCT. The backtest is blocked until it passes.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import config
from data.base import session_mask, timeframe_delta


@dataclass
class AlignmentResult:
    symbol: str
    session: str
    matched: int
    only_a: int
    only_b: int
    close_fail: int
    volume_fail: int
    best_shift_bars: int     # timestamp offset (in bars) that matches best; must be 0
    max_close_diff_pct: float
    median_volume_diff_pct: float

    @property
    def passed(self) -> bool:
        return (self.matched > 0 and self.best_shift_bars == 0 and self.close_fail == 0
                and self.volume_fail == 0 and self.only_a == 0 and self.only_b == 0)


def _close_match_rate(a: pd.DataFrame, b: pd.DataFrame) -> float:
    common = a.index.intersection(b.index)
    if len(common) == 0:
        return 0.0
    diff = (a.loc[common, "close"] - b.loc[common, "close"]).abs() / a.loc[common, "close"] * 100
    return float((diff <= config.ALIGN_CLOSE_TOL_PCT).mean())


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


def mismatches(a: pd.DataFrame, b: pd.DataFrame, session: str = "regular", before=None) -> pd.DataFrame:
    """Matched bars whose close or volume is outside tolerance, worst close difference first."""
    a, b = _overlap(a, b, session, before)
    common = a.index.intersection(b.index)
    ca, cb = a.loc[common], b.loc[common]
    out = pd.DataFrame({"close_a": ca["close"], "close_b": cb["close"],
                        "close_pct": (ca["close"] - cb["close"]).abs() / ca["close"] * 100,
                        "vol_a": ca["volume"], "vol_b": cb["volume"],
                        "vol_pct": (ca["volume"] - cb["volume"]).abs() / ca["volume"].where(ca["volume"] > 0) * 100})
    bad = (out["close_pct"] > config.ALIGN_CLOSE_TOL_PCT) | (out["vol_pct"] > config.ALIGN_VOLUME_TOL_PCT)
    return out[bad].sort_values(["close_pct", "vol_pct"], ascending=False)


def compare_bars(a: pd.DataFrame, b: pd.DataFrame, symbol: str, tf: str = "5m",
                 session: str = "regular", before=None) -> AlignmentResult:
    """Compare provider ``a`` (Alpaca) with ``b`` (Webull) on their overlapping days.

    ``before``: only dates before this one (pass today so a forming session is skipped).
    """
    a, b = _overlap(a, b, session, before)
    shift = detect_shift(a, b, tf)
    common = a.index.intersection(b.index)
    ca, cb = a.loc[common], b.loc[common]
    close_diff = (ca["close"] - cb["close"]).abs() / ca["close"] * 100
    vol_diff = (ca["volume"] - cb["volume"]).abs() / ca["volume"].where(ca["volume"] > 0) * 100
    return AlignmentResult(
        symbol=symbol, session=session, matched=len(common),
        only_a=len(a.index.difference(b.index)), only_b=len(b.index.difference(a.index)),
        close_fail=int((close_diff > config.ALIGN_CLOSE_TOL_PCT).sum()),
        volume_fail=int((vol_diff > config.ALIGN_VOLUME_TOL_PCT).sum()),
        best_shift_bars=shift,
        max_close_diff_pct=float(close_diff.max()) if len(common) else float("nan"),
        median_volume_diff_pct=float(vol_diff.median()) if len(common) else float("nan"),
    )
