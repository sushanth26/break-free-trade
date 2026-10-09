"""Module 4 — break risk 0-100 as price approaches a zone.

Factors: tests of the zone earlier today, approach speed and shape, approach
volume, regime against the level, news against the level.
"""
from __future__ import annotations

import pandas as pd

import config
from engine.scoring import load_weights, logistic_score, scale
from engine.zones import Zone


def zone_side(zone: Zone, price: float) -> str:
    """'support' if price is above the zone's middle, else 'resistance'."""
    return "support" if price >= zone.mid else "resistance"


def count_tests(zone: Zone, bars_today: pd.DataFrame) -> int:
    """Separate visits to the zone today (consecutive bars in the zone count once)."""
    inside = ((bars_today["low"] <= zone.top) & (bars_today["high"] >= zone.bottom)).to_numpy()
    return int(sum(1 for i, x in enumerate(inside) if x and (i == 0 or not inside[i - 1])))


def break_factors(zone: Zone, side: str, bars: pd.DataFrame, atr: float, rvol: pd.Series | None = None,
                  regime: str | None = None, news_against: bool = False) -> dict[str, float]:
    """Raw factors from 5m bars closed by now (the approach is the last APPROACH_BARS)."""
    n = config.APPROACH_BARS
    day = bars.index[-1].normalize()
    today = bars[bars.index.normalize() == day]
    recent = bars.iloc[-(n + 1):]
    closes = recent["close"].to_numpy()
    toward = (closes[1:] < closes[:-1]) if side == "support" else (closes[1:] > closes[:-1])
    against = {"support": ("bearish",), "resistance": ("bullish",)}[side]
    return {
        "recent_tests": count_tests(zone, today.iloc[:-1]) if len(today) > 1 else 0,
        "approach_speed_atr": abs(closes[-1] - closes[0]) / atr if len(closes) > 1 else 0.0,
        "approach_straight": float(toward.mean()) if len(toward) else 0.0,
        "approach_rvol": float(rvol.loc[recent.index].mean()) if rvol is not None else 1.0,
        "regime_against": 1.0 if regime in against else 0.5 if regime == "choppy" else 0.0,
        "news_against": float(news_against),
    }


def scale_break(f: dict[str, float]) -> dict[str, float]:
    caps = config.BREAK_CAPS
    return {k: scale(v, caps[k]) if k in caps else float(v) for k, v in f.items()}


def break_risk_score(factors: dict[str, float], weights: dict | None = None) -> float:
    return logistic_score(scale_break(factors), weights or load_weights()["break"])
