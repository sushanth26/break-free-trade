"""Module 8 — events that trigger alerts and Claude re-plans.

Compares the previous and current bar's features: bounce stage changes, VWAP
lost/reclaimed, gap filled, 10m cloud flip, opening-range break, regime
change and new headlines.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from engine.bounce import BounceUpdate

# Events that ask the re-planner for a new plan.
REPLAN_KINDS = {"regime_change", "gap_filled", "vwap_lost", "vwap_reclaimed", "cloud_flip"}


@dataclass(frozen=True)
class Event:
    time: pd.Timestamp
    symbol: str
    kind: str
    detail: dict = field(default_factory=dict, compare=False)

    @property
    def replan(self) -> bool:
        return self.kind in REPLAN_KINDS or (self.kind == "news" and self.detail.get("impact") == "high")


def _crossed(prev_a, prev_b, a, b) -> int:
    """+1 if a crossed above b, -1 if below, else 0."""
    if any(pd.isna(x) for x in (prev_a, prev_b, a, b)):
        return 0
    if prev_a <= prev_b and a > b:
        return 1
    if prev_a >= prev_b and a < b:
        return -1
    return 0


def bar_events(symbol: str, now: pd.Timestamp, prev: pd.Series | None, row: pd.Series,
               bounce: list[BounceUpdate] = (), regime: tuple[str, str] | None = None,
               headlines: pd.DataFrame | None = None) -> list[Event]:
    """Events on one bar close. ``regime`` = (previous, current) market regime."""
    ev: list[Event] = []
    for u in bounce:
        if u.changed:
            ev.append(Event(now, symbol, f"bounce_{u.stage}", {
                "direction": u.direction, "bottom": u.zone.bottom, "top": u.zone.top,
                "from": u.prev_stage, "reason": u.reason}))
    same_day = prev is not None and prev.name.normalize() == row.name.normalize()
    if same_day:
        x = _crossed(prev["close"], prev["vwap"], row["close"], row["vwap"])
        if x:
            ev.append(Event(now, symbol, "vwap_reclaimed" if x > 0 else "vwap_lost", {"vwap": row["vwap"]}))
        if pd.notna(row["prev_close"]) and pd.notna(row["day_open"]):
            up_gap = row["day_open"] > row["prev_close"]
            was = prev["day_low"] <= prev["prev_close"] if up_gap else prev["day_high"] >= prev["prev_close"]
            now_f = row["day_low"] <= row["prev_close"] if up_gap else row["day_high"] >= row["prev_close"]
            if now_f and not was and row["day_open"] != row["prev_close"]:
                ev.append(Event(now, symbol, "gap_filled", {"prev_close": row["prev_close"]}))
        if bool(prev["slow_bull_10m"]) != bool(row["slow_bull_10m"]):
            ev.append(Event(now, symbol, "cloud_flip", {"bullish": bool(row["slow_bull_10m"])}))
        for lvl, name in (("or_high", "or_break_up"), ("or_low", "or_break_down")):
            x = _crossed(prev["close"], prev[lvl], row["close"], row[lvl])
            if (x > 0 and name == "or_break_up") or (x < 0 and name == "or_break_down"):
                ev.append(Event(now, symbol, name, {"level": row[lvl]}))
    if regime and regime[0] != regime[1]:
        ev.append(Event(now, symbol, "regime_change", {"from": regime[0], "to": regime[1]}))
    if headlines is not None:
        for _, h in headlines.iterrows():
            ev.append(Event(now, symbol, "news", {"id": h["id"], "headline": h["headline"],
                                                   "published_at": h["published_at"]}))
    return ev
