"""Module 3 — level strength 0-100 per zone.

Factors: reaction size after each pivot, timeframe confluence, other
confluence (round numbers, prior-day high/low/close), volume at the level,
role flip, width and age. Only bars closed by ``now`` are used.
"""
from __future__ import annotations

import pandas as pd

import config
from engine.profile import round_levels
from engine.scoring import load_weights, logistic_score, scale
from engine.zones import Zone

REACTION_BARS = 12   # 5m bars after a pivot used to measure its reaction (1 hour)


def strength_factors(zone: Zone, bars: pd.DataFrame, atr: float, round_step: float,
                     prior_levels: tuple[float, ...] = ()) -> dict[str, float]:
    """Raw factor values. ``bars`` = 5m bars closed by now (any sessions)."""
    pad = config.ROUND_CONFLUENCE_ATR * atr
    lo, hi = zone.bottom - pad, zone.top + pad
    highs, lows = bars["high"].to_numpy(), bars["low"].to_numpy()
    pos = bars.index.searchsorted

    reactions = []
    for p in zone.pivots:
        i = pos(p.time)
        after = slice(i + 1, min(i + 1 + REACTION_BARS, len(bars)))
        if after.start >= after.stop:
            continue
        move = p.price - lows[after].min() if p.kind == "high" else highs[after].max() - p.price
        reactions.append(max(move, 0.0) / atr)

    loop = bars.iloc[-config.ZONE_DEFAULT.loopback:]
    at_level = (loop["low"] <= zone.top) & (loop["high"] >= zone.bottom)
    avg_vol = loop["volume"].mean()
    vol_ratio = loop.loc[at_level, "volume"].mean() / avg_vol if at_level.any() and avg_vol > 0 else 0.0

    rounds = round_levels((zone.top + zone.bottom) / 2, round_step, n=2)
    newest = max((p.time for p in zone.pivots), default=zone.created_at)
    kinds = {p.kind for p in zone.pivots}
    return {
        "reaction_atr": sum(reactions) / len(reactions) if reactions else 0.0,
        "tf_count": len(zone.timeframes),
        "pivots": len(zone.pivots),
        "touches": max(zone.strength_raw - config.ZONE_PIVOT_WEIGHT * len(zone.pivots), 0),
        "round_number": float(any(lo <= r <= hi for r in rounds)),
        "prior_day_level": float(any(lo <= x <= hi for x in prior_levels if pd.notna(x))),
        "volume_ratio": float(vol_ratio),
        "role_flip": float(kinds == {"high", "low"}),
        "width_atr": zone.width / atr,
        "age_bars": float(len(bars) - pos(newest)),
    }


def scale_strength(f: dict[str, float]) -> dict[str, float]:
    caps = config.STRENGTH_CAPS
    return {k: scale(v, caps[k]) if k in caps else float(v) for k, v in f.items()}


def strength_score(factors: dict[str, float], weights: dict | None = None) -> float:
    return logistic_score(scale_strength(factors), weights or load_weights()["strength"])
