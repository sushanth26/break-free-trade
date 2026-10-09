"""The per-symbol engine: modules 1-8 on every 5m bar close.

Backtest and live both call ``SymbolEngine.on_bar`` with the same inputs:
the closed bar's feature row, the bars closed so far, the zones in force and
a market/news context. It returns events, watch alerts, trade plans that
passed every rule, and the signals it skipped (with the reason).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

import config
from engine.aplus import aplus_score
from engine.bounce import CONFIRMED, REJECTION, BounceTracker, BounceUpdate
from engine.break_risk import break_factors, break_risk_score
from engine.events import Event, bar_events
from engine.profile import round_step
from engine.regime import against
from engine.scoring import zone_score
from engine.settings import EngineSettings
from engine.strength import strength_factors, strength_score
from engine.trade import TradePlan, plan_trade
from engine.zones import Zone

WATCH_DIST_ATR = 0.5


@dataclass
class BarContext:
    """Market and news state known at the bar close."""
    regime: str = "choppy"
    gap_dir: str = ""
    regime_confirmed: bool = False
    prev_regime: str | None = None
    catalyst: bool = False
    news_bias: str = ""               # "bullish" / "bearish" / "" from the news judge
    in_news_window: bool = False
    earnings_week: bool = False
    headlines: pd.DataFrame | None = None
    spread: float | None = None

    def news_against(self, direction: str) -> bool:
        return (direction == "long" and self.news_bias == "bearish") or \
               (direction == "short" and self.news_bias == "bullish")


@dataclass
class BarResult:
    events: list[Event] = field(default_factory=list)
    watch: list[tuple[Zone, float]] = field(default_factory=list)
    plans: list[TradePlan] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    updates: list[BounceUpdate] = field(default_factory=list)


class SymbolEngine:
    def __init__(self, symbol: str, zones_at: Callable[[pd.Timestamp], list[Zone]],
                 settings: EngineSettings = EngineSettings()):
        self.symbol = symbol
        self.zones_at = zones_at
        self.settings = settings
        self.trackers: dict[tuple, BounceTracker] = {}
        self.prev_row: pd.Series | None = None

    # ------------------------------------------------------------------ scoring
    def score_zone(self, zone: Zone, side: str, hist: pd.DataFrame, row: pd.Series, ctx: BarContext,
                   rvol: pd.Series | None = None) -> float:
        atr = row["atr"]
        sf = strength_factors(zone, hist, atr, round_step(row["close"]),
                              (row["prev_high"], row["prev_low"], row["prev_close"]))
        direction = "long" if side == "support" else "short"
        bf = break_factors(zone, side, hist, atr, rvol, ctx.regime, ctx.news_against(direction))
        return zone_score(strength_score(sf), break_risk_score(bf))

    # ------------------------------------------------------------------ main step
    def on_bar(self, t: pd.Timestamp, row: pd.Series, hist: pd.DataFrame, ctx: BarContext,
               rvol: pd.Series | None = None) -> BarResult:
        """``t`` = bar start; ``row`` = its feature row; ``hist`` = 5m bars up to and including t."""
        now = t + pd.Timedelta("5min")
        res = BarResult()
        zones = self.zones_at(now)
        atr = row["atr"]
        prev = self.prev_row
        self.prev_row = row
        if prev is None or not atr == atr or atr <= 0:
            res.events = bar_events(self.symbol, now, prev, row, regime=self._regime_pair(ctx), headlines=ctx.headlines)
            return res

        # keep trackers for zones in force (and any mid-rejection)
        live = {}
        for z in zones:
            for d in ("long", "short") if self.settings.allow_short else ("long",):
                key = (z.bottom, z.top, d)
                live[key] = self.trackers.get(key) or BounceTracker(z, d)
        for key, tr in self.trackers.items():
            if key not in live and tr.stage == REJECTION:
                live[key] = tr
        self.trackers = live

        bar = {k: row[k] for k in ("open", "high", "low", "close", "volume")}
        vol_avg = row["vol_avg"] if row["vol_avg"] == row["vol_avg"] else 0.0
        res.updates = [tr.step(bar, prev["close"], atr, vol_avg) for tr in self.trackers.values()]
        res.events = bar_events(self.symbol, now, prev, row, res.updates, self._regime_pair(ctx), ctx.headlines)

        for z in zones:
            near = z.top if row["close"] >= z.mid else z.bottom
            was = abs(prev["close"] - near) <= WATCH_DIST_ATR * atr
            if abs(row["close"] - near) <= WATCH_DIST_ATR * atr and not was:
                side = "support" if row["close"] >= z.mid else "resistance"
                res.watch.append((z, self.score_zone(z, side, hist, row, ctx, rvol)))

        want = CONFIRMED if self.settings.entry_mode == "confirmed" else REJECTION
        for u in res.updates:
            if u.stage != want or not u.changed:
                continue
            plan, why = self._evaluate(u, zones, hist, row, ctx, now, rvol)
            if plan is not None:
                res.plans.append(plan)
            else:
                res.skipped.append({"symbol": self.symbol, "time": now, "direction": u.direction,
                                    "bottom": u.zone.bottom, "top": u.zone.top, "reason": why})
        res.plans.sort(key=lambda p: (p.aplus, p.zone_score), reverse=True)
        return res

    def _regime_pair(self, ctx: BarContext):
        return (ctx.prev_regime, ctx.regime) if ctx.prev_regime is not None else None

    def _evaluate(self, u: BounceUpdate, zones, hist, row, ctx: BarContext, now, rvol
                  ) -> tuple[TradePlan | None, str]:
        s = self.settings
        if not u.entry_ok:
            return None, u.reason or "entry not allowed"
        hhmm = now.strftime("%H:%M")
        premarket = bool(row["premarket"])
        if not (premarket or row["regular"]):
            return None, "outside sessions"
        if hhmm > config.ENTRY_CUTOFF:
            return None, "after entry cutoff"
        if s.time_filter and not (s.time_filter[0] <= hhmm <= s.time_filter[1]):
            return None, "time-of-day filter"
        if s.news_filter and ctx.in_news_window:
            return None, "inside macro news window"
        if s.news_filter and ctx.news_against(u.direction):
            return None, "news against"
        mkt_against = against(ctx.regime, ctx.gap_dir, u.direction)
        if s.require_regime_agree and mkt_against:
            return None, f"regime {ctx.regime} against {u.direction}"

        side = "support" if u.direction == "long" else "resistance"
        score = self.score_zone(u.zone, side, hist, row, ctx, rvol)
        if score < s.min_zone_score:
            return None, f"zone score {score:.0f} < {s.min_zone_score:g}"

        size = (config.PREMARKET_SIZE if premarket else 1.0) * (0.5 if ctx.earnings_week else 1.0)
        plan, why = plan_trade(self.symbol, u.direction, u.entry_price, u.rej_low, u.rej_high, u.zone, zones,
                               row["atr"], round_step(row["close"]), now, size_mult=size, min_t1_r=s.min_t1_r)
        if plan is None:
            return None, why

        sf_conf = len(u.zone.timeframes) >= 2
        if not sf_conf:
            f = strength_factors(u.zone, hist, row["atr"], round_step(row["close"]),
                                 (row["prev_high"], row["prev_low"], row["prev_close"]))
            sf_conf = bool(f["round_number"] or f["prior_day_level"])
        ap = aplus_score(u.direction, catalyst=ctx.catalyst, confluence=sf_conf,
                         slow_bull_5m=bool(row["slow_bull"]), slow_bull_10m=bool(row["slow_bull_10m"]),
                         confirmed=u.stage == CONFIRMED, rvol=float(row["rvol"]), r_to_t1=plan.r_to_t1,
                         market_against=mkt_against)
        if premarket:
            if not s.allow_premarket or ap.grade != "A+":
                return None, "premarket needs A+"
            if ctx.spread is not None and ctx.spread > config.PREMARKET_MAX_SPREAD_ATR * row["atr"]:
                return None, "spread too wide"
        elif ap.grade == "B":
            return None, f"grade B ({ap.score}/7)"
        elif ap.grade == "A" and not ctx.regime_confirmed:
            return None, "A setup before regime confirmed"
        if s.aplus_only and ap.grade != "A+":
            return None, f"A+ only ({ap.score}/7)"

        plan.grade, plan.aplus, plan.zone_score = ap.grade, ap.score, score
        plan.regime, plan.premarket = ctx.regime, premarket
        plan.notes = {"entry_mode": s.entry_mode, "catalyst": ctx.catalyst, "time_of_day": hhmm,
                      **{f"ap_{k}": v for k, v in ap.checks.items()}}
        return plan, ""
