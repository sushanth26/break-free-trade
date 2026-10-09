"""Module 1 — StockProfile: the per-stock yardstick every distance is measured in.

Built from bars closed by ``as_of``: daily ATR, 5m ATR (regular hours,
overnight gaps ignored), RVOL baseline by time slot, round-number step, spread.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

import config
from data.base import closed_bars, regular_hours, to_ts
from engine import indicators as ind


@dataclass(frozen=True)
class StockProfile:
    symbol: str
    as_of: pd.Timestamp
    last_price: float
    atr_5m: float
    daily_atr: float
    round_step: float
    spread: float | None = None
    rvol_baseline: dict[str, float] = field(default_factory=dict)  # "HH:MM" -> avg volume

    def atr_dist(self, multiple: float) -> float:
        """A distance expressed as a multiple of 5m ATR, in dollars."""
        return multiple * self.atr_5m

    def spread_atr(self) -> float | None:
        return None if self.spread is None else self.spread / self.atr_5m


def round_step(price: float) -> float:
    for upper, step in config.ROUND_STEPS:
        if price < upper:
            return step
    return config.ROUND_STEPS[-1][1]


def round_levels(price: float, step: float, n: int = 2) -> list[float]:
    """The ``n`` round numbers on each side of ``price``."""
    base = math.floor(price / step) * step
    return [round(base + k * step, 2) for k in range(-n + 1, n + 1)]


def build_profile(symbol: str, bars_5m: pd.DataFrame, bars_daily: pd.DataFrame, as_of,
                  spread: float | None = None) -> StockProfile:
    as_of = to_ts(as_of)
    intraday = regular_hours(closed_bars(bars_5m, "5m", as_of))
    daily = closed_bars(bars_daily, "D", as_of)
    if len(intraday) < config.ATR_PERIOD or len(daily) < config.DAILY_ATR_PERIOD:
        raise ValueError(f"{symbol}: not enough history before {as_of} to build a profile")
    atr_5m = float(ind.atr(intraday, config.ATR_PERIOD, ignore_gaps=True).iloc[-1])
    daily_atr = float(ind.atr(daily, config.DAILY_ATR_PERIOD).iloc[-1])
    last = float(intraday["close"].iloc[-1])

    days = pd.Index(ind.session_dates(intraday.index)).unique()[-config.RVOL_LOOKBACK_DAYS:]
    recent = intraday[pd.Index(ind.session_dates(intraday.index)).isin(days)]
    baseline = recent["volume"].groupby(ind.time_slot(recent.index)).mean().to_dict()

    return StockProfile(symbol=symbol.upper(), as_of=as_of, last_price=last, atr_5m=atr_5m,
                        daily_atr=daily_atr, round_step=round_step(last), spread=spread,
                        rvol_baseline=baseline)
