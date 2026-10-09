"""Module 5 — market regime from SPY / QQQ / SMH.

Per symbol, at each 5m bar close:
  gap_filled   the day gapped and price has traded back to the prior close
  gap_filling  the day gapped and price is moving back toward the prior close
  bullish      above VWAP, 10m 34/50 cloud bullish, not below the opening range
  bearish      the mirror
  choppy       anything else
Market regime = SPY/QQQ agreement, SMH breaks a tie; otherwise choppy.
A regime is confirmed after REGIME_CONFIRM_BARS bars in the same state.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

REGIMES = ("bullish", "gap_filling", "gap_filled", "choppy", "bearish")


def symbol_regime(feats: pd.DataFrame) -> pd.DataFrame:
    """Regime and gap direction for every bar of one symbol's feature table."""
    f = feats
    price = f["close"]
    gap = f["day_open"] - f["prev_close"]
    gap_min = config.REGIME_GAP_MIN_DAILY_ATR * f["daily_atr"].fillna(price * 0.01)
    gap_dir = np.where(gap >= gap_min, "up", np.where(gap <= -gap_min, "down", ""))
    filled = ((gap_dir == "up") & (f["day_low"] <= f["prev_close"])) | \
             ((gap_dir == "down") & (f["day_high"] >= f["prev_close"]))
    filling = ((gap_dir == "up") & (price < f["vwap"])) | ((gap_dir == "down") & (price > f["vwap"]))
    above_or = ~(price < f["or_low"])
    below_or = ~(price > f["or_high"])
    bull = (price > f["vwap"]) & f["slow_bull_10m"] & above_or
    bear = (price < f["vwap"]) & ~f["slow_bull_10m"] & below_or
    regime = np.select([filled & ~bull & ~bear, filling & ~filled, bull, bear],
                       ["gap_filled", "gap_filling", "bullish", "bearish"], "choppy")
    return pd.DataFrame({"regime": regime, "gap_dir": gap_dir}, index=f.index)


def market_regime(per_symbol: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Combine symbol regimes (SPY, QQQ, SMH) into one market regime per bar.

    Output is indexed by bar CLOSE time (when the value becomes known), with
    columns regime, gap_dir, confirmed.
    """
    syms = [s for s in config.REGIME_SYMBOLS if s in per_symbol]
    if not syms:
        raise ValueError("need at least one of " + ", ".join(config.REGIME_SYMBOLS))
    frames = {s: symbol_regime(per_symbol[s]) for s in syms}
    idx = frames[syms[0]].index
    for s in syms[1:]:
        idx = idx.intersection(frames[s].index)
    reg = pd.DataFrame({s: frames[s].loc[idx, "regime"] for s in syms})
    lead = syms[0]
    out = reg[lead].copy()
    if len(syms) >= 2:
        a, b = reg[syms[0]], reg[syms[1]]
        tie = reg[syms[2]] if len(syms) > 2 else pd.Series("choppy", index=idx)
        out = np.where(a == b, a, np.where(tie == a, a, np.where(tie == b, b, "choppy")))
        out = pd.Series(out, index=idx)
    run = (out != out.shift()).cumsum()
    streak = out.groupby(run).cumcount() + 1
    res = pd.DataFrame({"regime": out, "gap_dir": frames[lead].loc[idx, "gap_dir"],
                        "confirmed": streak >= config.REGIME_CONFIRM_BARS}, index=idx)
    res.index = res.index + pd.Timedelta("5min")
    return res


def regime_at(market: pd.DataFrame, now: pd.Timestamp) -> tuple[str, str, bool]:
    """(regime, gap_dir, confirmed) known at ``now``; choppy/unconfirmed before any data."""
    k = market.index.searchsorted(now, side="right") - 1
    if k < 0:
        return "choppy", "", False
    row = market.iloc[k]
    return row["regime"], row["gap_dir"], bool(row["confirmed"])


def against(regime: str, gap_dir: str, direction: str) -> bool:
    """True if the market regime opposes a trade direction ('long'/'short')."""
    if direction == "long":
        return regime == "bearish" or (regime == "gap_filling" and gap_dir == "up")
    return regime == "bullish" or (regime == "gap_filling" and gap_dir == "down")


class RegimeLookup:
    """Fast ``regime_at`` for backtests (array search instead of DataFrame access)."""

    def __init__(self, market: pd.DataFrame):
        self.times = market.index.as_unit("ns").asi8
        self.regime = market["regime"].to_numpy()
        self.gap = market["gap_dir"].to_numpy()
        self.conf = market["confirmed"].to_numpy()

    def __call__(self, now: pd.Timestamp) -> tuple[str, str, bool]:
        k = int(np.searchsorted(self.times, now.value, side="right")) - 1
        if k < 0:
            return "choppy", "", False
        return self.regime[k], self.gap[k], bool(self.conf[k])
