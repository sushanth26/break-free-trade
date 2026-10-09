"""Module 2 — support/resistance zones on any timeframe, with no lookahead.

Port of the TradingView "Support Resistance Channels" method (pivot period,
channel width %, min strength, max zones, loopback), so zones can be checked
against the chart:

1. Pivot highs (from highs) and pivot lows (from lows) with ``pivot_period``
   bars each side. A pivot is only known ``pivot_period`` bars after it forms;
   it is usable from the close of that confirmation bar.
2. On each new confirmed pivot, every recent pivot seeds a channel that
   absorbs other pivots while the channel stays within the max width
   (channel_width_pct of the last ``range_bars`` high-low range). Strength =
   20 per pivot + 1 per bar in the loopback whose high or low is inside it.
3. The strongest channels (>= min_strength pivots) are kept greedily; any
   channel overlapping a stronger one is dropped. Up to ``max_zones``.

Zones stay fixed between pivot confirmations, as on the chart.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

import config
from config import ZoneConfig
from data.base import bar_close_times, closed_bars, resample, to_ts


@dataclass(frozen=True)
class Pivot:
    time: pd.Timestamp       # bar the pivot formed on
    price: float
    kind: str                # "high" or "low"
    confirmed_at: pd.Timestamp


@dataclass(frozen=True)
class Zone:
    top: float
    bottom: float
    timeframes: tuple[str, ...]
    pivots: tuple[Pivot, ...]
    strength_raw: int        # TradingView strength (20 per pivot + touches)
    created_at: pd.Timestamp  # first time the zone is usable

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def width(self) -> float:
        return self.top - self.bottom

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top

    def overlaps(self, other: "Zone") -> bool:
        return self.bottom <= other.top and other.bottom <= self.top


def find_pivots(bars: pd.DataFrame, period: int, tf: str) -> list[Pivot]:
    """Pivot highs/lows: the center bar is the window extreme and strictly beyond
    the ``period`` bars before it (ties go to the earlier bar). As on TradingView,
    a bar that is both a pivot high and low counts as a pivot high only."""
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    closes = bar_close_times(bars, tf)
    times = bars.index
    out: list[Pivot] = []
    for i in range(period, len(bars) - period):
        win_h = high[i - period:i + period + 1]
        win_l = low[i - period:i + period + 1]
        conf = closes[i + period]
        if high[i] == win_h.max() and high[i] > high[i - period:i].max():
            out.append(Pivot(times[i], float(high[i]), "high", conf))
        elif low[i] == win_l.min() and low[i] < low[i - period:i].min():
            out.append(Pivot(times[i], float(low[i]), "low", conf))
    return out


def _channels(pivots: list[Pivot], high: np.ndarray, low: np.ndarray,
              cwidth: float, cfg: ZoneConfig) -> list[tuple[float, float, int, list[Pivot]]]:
    """Steps 2-3 for one recompute. ``pivots`` newest first; high/low = loopback bars."""
    vals = [p.price for p in pivots]
    cands = []
    for seed in vals:
        lo = hi = seed
        members = []
        for k, cpp in enumerate(vals):
            wdth = hi - min(lo, cpp) if cpp <= hi else max(hi, cpp) - lo
            if wdth <= cwidth:
                if cpp <= hi:
                    lo = min(lo, cpp)
                else:
                    hi = max(hi, cpp)
                members.append(pivots[k])
        touches = int((((high <= hi) & (high >= lo)) | ((low <= hi) & (low >= lo))).sum())
        cands.append([config.ZONE_PIVOT_WEIGHT * len(members) + touches, hi, lo, members])

    chosen = []
    for _ in range(len(cands)):
        best = max((c for c in cands if c[0] >= cfg.min_strength * config.ZONE_PIVOT_WEIGHT),
                   key=lambda c: c[0], default=None)
        if best is None:
            break
        strength, hh, ll, members = best
        chosen.append((hh, ll, strength, members))
        for c in cands:   # drop candidates overlapping the chosen channel (incl. itself)
            if ll <= c[1] <= hh or ll <= c[2] <= hh:
                c[0] = -1
        if len(chosen) >= cfg.max_zones:
            break
    return chosen


def zone_history(bars: pd.DataFrame, tf: str, cfg: ZoneConfig = config.ZONE_DEFAULT
                 ) -> list[tuple[pd.Timestamp, list[Zone]]]:
    """Zone sets over time: [(usable_from, zones)], one entry per pivot confirmation.

    Each set uses only bars up to and including its confirmation bar.
    """
    pivots = find_pivots(bars, cfg.pivot_period, tf)
    if not pivots:
        return []
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    closes = bar_close_times(bars, tf)
    pos = {t: i for i, t in enumerate(bars.index)}
    close_pos = {t: i for i, t in enumerate(closes)}
    by_conf: dict[pd.Timestamp, list[Pivot]] = {}
    for p in pivots:
        by_conf.setdefault(p.confirmed_at, []).append(p)

    history = []
    for conf_time in sorted(by_conf):
        cur = close_pos[conf_time]
        # pivots confirmed within the loopback, newest first (as TradingView stores them)
        recent = [p for p in pivots if p.confirmed_at <= conf_time
                  and cur - close_pos[p.confirmed_at] <= cfg.loopback]
        recent.sort(key=lambda p: pos[p.time], reverse=True)
        rng = slice(max(0, cur - cfg.range_bars + 1), cur + 1)
        cwidth = (high[rng].max() - low[rng].min()) * cfg.channel_width_pct / 100
        lb = slice(max(0, cur - cfg.loopback), cur + 1)
        zones = [Zone(top=hh, bottom=ll, timeframes=(tf,), pivots=tuple(sorted(m, key=lambda p: p.time)),
                      strength_raw=s, created_at=conf_time)
                 for hh, ll, s, m in _channels(recent, high[lb], low[lb], cwidth, cfg)]
        history.append((conf_time, zones))
    return history


def zones_at(history: list[tuple[pd.Timestamp, list[Zone]]], now) -> list[Zone]:
    """The zone set in force at ``now`` (latest recompute usable by then)."""
    now = to_ts(now)
    current: list[Zone] = []
    for usable_from, zones in history:
        if usable_from > now:
            break
        current = zones
    return current


def compute_zones(bars: pd.DataFrame, tf: str, now, cfg: ZoneConfig = config.ZONE_DEFAULT) -> list[Zone]:
    """Zones for one timeframe at ``now`` from bars of that timeframe."""
    return zones_at(zone_history(closed_bars(bars, tf, to_ts(now)), tf, cfg), now)


def merge_zones(zones: list[Zone]) -> list[Zone]:
    """Merge overlapping zones from different timeframes into one confluence zone."""
    merged: list[Zone] = []
    for z in sorted(zones, key=lambda z: z.bottom):
        if merged and merged[-1].overlaps(z) and not set(z.timeframes) <= set(merged[-1].timeframes):
            m = merged[-1]
            merged[-1] = replace(
                m, top=max(m.top, z.top), bottom=min(m.bottom, z.bottom),
                timeframes=tuple(sorted(set(m.timeframes) | set(z.timeframes), key=config.TIMEFRAMES.index)),
                pivots=tuple(sorted(m.pivots + z.pivots, key=lambda p: p.time)),
                strength_raw=m.strength_raw + z.strength_raw,
                created_at=max(m.created_at, z.created_at))
        else:
            merged.append(z)
    return merged


def multi_timeframe_zones(bars_5m: pd.DataFrame, timeframes: tuple[str, ...], now,
                          cfg: ZoneConfig = config.ZONE_DEFAULT,
                          bars_daily: pd.DataFrame | None = None) -> list[Zone]:
    """Zones from several timeframes at ``now``; higher timeframes are resampled
    from 5m and only their closed bars are used."""
    now = to_ts(now)
    zones: list[Zone] = []
    for tf in timeframes:
        if tf == "5m":
            src = bars_5m
        elif tf == "D" and bars_daily is not None:
            src = bars_daily
        else:
            src = resample(bars_5m, tf)
        zones += compute_zones(src, tf, now, cfg)
    return merge_zones(zones) if config.ZONE_MERGE_OVERLAP else zones


def label_zones(zones: list[Zone], price: float) -> list[tuple[str, Zone]]:
    """Chart labels: S1, S2... below price (nearest first), R1, R2... above."""
    supports = sorted((z for z in zones if z.mid <= price), key=lambda z: price - z.mid)
    resists = sorted((z for z in zones if z.mid > price), key=lambda z: z.mid - price)
    return [(f"S{i + 1}", z) for i, z in enumerate(supports)] + \
           [(f"R{i + 1}", z) for i, z in enumerate(resists)]
