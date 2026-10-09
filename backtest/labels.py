"""Day 2 — find every zone touch and label it hold / break.

A touch: price arrives at a zone from outside (prior close above a support
zone's top and this bar's low reaches the top; mirror for resistance).
Factors are measured from bars closed BEFORE the touch bar, with the zones
in force at that time, so labels never peek ahead.

Outcome (same session, conservative within a bar):
  break = price goes BREAK_ATR beyond the far edge first
  held  = price moves HOLD_MOVE_ATR away from the near edge first
  none  = neither by the session close (excluded from training)
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

import config
from engine.break_risk import break_factors, break_risk_score
from engine.strength import strength_factors, strength_score
from engine.zones import Zone

ZoneSource = Callable[[pd.Timestamp], list[Zone]]


@dataclass
class ZoneTimeline:
    """Zone sets that change only at known times; lookup by time is O(log n)."""
    times: list[pd.Timestamp]
    sets: list[list[Zone]]

    def __call__(self, now: pd.Timestamp) -> list[Zone]:
        k = bisect_right(self.times, now) - 1
        return self.sets[k] if k >= 0 else []


def label_outcome(side: str, zone: Zone, atr: float, high: np.ndarray, low: np.ndarray,
                  start: int, end: int) -> tuple[str, int, float, float]:
    """Scan bars [start, end) after a touch at bar start.

    Returns (outcome, resolve_index, reaction_atr, overshoot_atr).
    """
    hold_lvl = zone.top + config.HOLD_MOVE_ATR * atr if side == "support" else zone.bottom - config.HOLD_MOVE_ATR * atr
    break_lvl = zone.bottom - config.BREAK_ATR * atr if side == "support" else zone.top + config.BREAK_ATR * atr
    reaction = overshoot = 0.0
    for j in range(start, end):
        if side == "support":
            overshoot = max(overshoot, (zone.bottom - low[j]) / atr)
            broke, held = low[j] <= break_lvl, high[j] >= hold_lvl and j > start
            reaction = max(reaction, (high[j] - zone.top) / atr) if j > start else reaction
        else:
            overshoot = max(overshoot, (high[j] - zone.top) / atr)
            broke, held = high[j] >= break_lvl, low[j] <= hold_lvl and j > start
            reaction = max(reaction, (zone.bottom - low[j]) / atr) if j > start else reaction
        if broke:
            return "break", j, reaction, overshoot
        if held:
            return "held", j, reaction, overshoot
    return "none", end - 1, reaction, overshoot


def find_touches(bars: pd.DataFrame, feats: pd.DataFrame, zones_at: ZoneSource,
                 round_step: float, regime: pd.Series | None = None,
                 symbol: str = "") -> pd.DataFrame:
    """Every zone touch in regular hours with factors, scores and outcome."""
    reg = feats["regular"].to_numpy()
    idx = bars.index
    high, low, close = (bars[c].to_numpy() for c in ("high", "low", "close"))
    atr = feats["atr"].to_numpy()
    day = idx.normalize()
    closes_at = idx + pd.Timedelta("5min")
    day_end = pd.Series(np.arange(len(idx)), index=idx).groupby(day).transform("max").to_numpy()
    busy_until: dict[tuple[float, float], int] = {}
    rows = []
    for i in range(1, len(idx)):
        if not reg[i] or not reg[i - 1] or day[i] != day[i - 1] or not np.isfinite(atr[i - 1]):
            continue
        prev_t = closes_at[i - 1]
        a = atr[i - 1]
        for z in zones_at(prev_t):
            key = (z.bottom, z.top)
            if busy_until.get(key, -1) >= i:
                continue
            if close[i - 1] > z.top and low[i] <= z.top:
                side = "support"
            elif close[i - 1] < z.bottom and high[i] >= z.bottom:
                side = "resistance"
            else:
                continue
            outcome, j, reaction, overshoot = label_outcome(side, z, a, high, low, i, day_end[i] + 1)
            busy_until[key] = j
            hist = bars.iloc[:i]
            row_f = feats.iloc[i - 1]
            sf = strength_factors(z, hist, a, round_step, (row_f["prev_high"], row_f["prev_low"], row_f["prev_close"]))
            reg_state = regime.asof(prev_t) if regime is not None and len(regime) else None
            bf = break_factors(z, side, hist, a, feats["rvol"].iloc[:i], reg_state if isinstance(reg_state, str) else None)
            rows.append({
                "symbol": symbol, "time": idx[i], "side": side, "bottom": z.bottom, "top": z.top,
                "timeframes": "+".join(z.timeframes), "atr": a, "distance_atr": abs(close[i - 1] - z.mid) / a,
                "outcome": outcome, "held": outcome == "held", "reaction_atr": reaction,
                "overshoot_atr": overshoot,
                **{f"s_{k}": v for k, v in sf.items()}, **{f"b_{k}": v for k, v in bf.items()},
                "strength": strength_score(sf), "break_risk": break_risk_score(bf),
            })
    return pd.DataFrame(rows)
