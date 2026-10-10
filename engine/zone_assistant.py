"""Zone assistant -- alerts only, never places orders.

Pure functions/state machines for the watchlist's zone alerts: scoring (shared
with the simple-bounce and zone-touch-scalp backtests, so "same engine for
backtest and live" holds here too), labelling, the approach/at-zone/
reclaim/break alert stages, and the Day 3-style forward-test outcome that
follows every "at zone" alert. No I/O here -- printing, Telegram, SQLite and
the Webull feed live in live/ and scripts/.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config
from engine.break_risk import break_factors, break_risk_score
from engine.profile import round_step
from engine.scoring import zone_score
from engine.strength import strength_factors, strength_score
from engine.zones import Zone, label_zones

APPROACHING, AT_ZONE, RECLAIMED, BROKEN = "approaching", "at_zone", "reclaimed", "broken"


# ------------------------------------------------------------------ scoring + labelling

def zone_score_from_bars(zone: Zone, side: str, hist, row, rvol, weights: dict) -> float:
    """The same strength/break-risk scoring the main engine and both strategy
    backtests use, with a supplied (already-learned) weights dict."""
    sf = strength_factors(zone, hist, row["atr"], round_step(row["close"]),
                          (row["prev_high"], row["prev_low"], row["prev_close"]))
    bf = break_factors(zone, side, hist, row["atr"], rvol, None, False)
    s = strength_score(sf, weights["strength"])
    b = break_risk_score(bf, weights["break"])
    return zone_score(s, b, weights["w_s"], weights["w_b"], weights)


def hold_rate(score: float, bands: dict[str, float] = config.ZONE_HOLD_RATE_BY_BAND) -> float:
    """Historical hold rate for a score, from the Day 3 score bands."""
    if score >= 80:
        return bands["80+"]
    if score >= 50:
        return bands["50-79"]
    return bands["<50"]


@dataclass(frozen=True)
class LabelledZone:
    label: str          # "S1", "R1", ...
    zone: Zone
    score: float
    distance_atr: float


def labelled_zones(zones: list[Zone], price: float, atr: float, hist, row, rvol, weights: dict,
                   max_dist_atr: float = config.ZONE_ASSISTANT_MAX_DIST_ATR) -> list[LabelledZone]:
    """S1, S2... / R1, R2... with scores, zones beyond ``max_dist_atr`` dropped."""
    out = []
    for label, z in label_zones(zones, price):
        dist = (max(z.bottom - price, 0.0) if z.bottom > price else max(price - z.top, 0.0)) / atr
        if dist > max_dist_atr:
            continue
        side = "support" if z.mid <= price else "resistance"
        score = zone_score_from_bars(z, side, hist, row, rvol, weights)
        out.append(LabelledZone(label, z, score, dist))
    return out


# ------------------------------------------------------------------ alert stages

@dataclass
class ZoneAlert:
    stage: str
    symbol: str
    label: str
    zone: Zone
    text_args: dict


@dataclass
class ZoneWatchTracker:
    """One instance per physical zone (by its bottom/top). Tracks the
    approach -> at-zone -> reclaim/break cycle, with a cool-down after a break.
    """
    key: tuple[float, float]
    stage: str = "idle"                 # idle | approaching | at_zone | cooldown
    direction: str | None = None        # "long" (visited as support) or "short" (as resistance), set at at_zone
    wick_extreme: float = field(default=float("nan"))   # lowest low (long) / highest high (short) seen in-zone
    cooldown_left: int = 0

    def step(self, symbol: str, label: str, zone: Zone, score: float, bar: dict, prev_close: float,
            atr: float) -> list[ZoneAlert]:
        out: list[ZoneAlert] = []
        if self.stage == "cooldown":
            self.cooldown_left -= 1
            if self.cooldown_left <= 0:
                self.stage = "idle"
            else:
                return out

        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        near_dist = min(abs(c - zone.top), abs(c - zone.bottom)) / atr

        if self.stage == "idle":
            if near_dist <= config.ZONE_ASSISTANT_APPROACH_ATR and score >= 50 and not zone.contains(c):
                self.stage = "approaching"
                out.append(ZoneAlert(APPROACHING, symbol, label, zone, {"score": score}))

        if self.stage in ("idle", "approaching"):
            touched = l <= zone.top and h >= zone.bottom
            if touched:
                self.direction = "long" if prev_close > zone.top else "short"
                self.stage = "at_zone"
                self.wick_extreme = l if self.direction == "long" else h
                out.append(ZoneAlert(AT_ZONE, symbol, label, zone, {}))
                return out

        if self.stage == "at_zone":
            if self.direction == "long":
                self.wick_extreme = min(self.wick_extreme, l)
                if c < zone.bottom - config.ZONE_ASSISTANT_BREAK_ATR * atr:
                    self.stage = "cooldown"
                    self.cooldown_left = config.ZONE_ASSISTANT_COOLDOWN_BARS
                    out.append(ZoneAlert(BROKEN, symbol, label, zone, {"close": c}))
                elif c > zone.top:
                    self.stage = "idle"
                    out.append(ZoneAlert(RECLAIMED, symbol, label, zone, {"close": c, "wick": self.wick_extreme}))
            else:
                self.wick_extreme = max(self.wick_extreme, h)
                if c > zone.top + config.ZONE_ASSISTANT_BREAK_ATR * atr:
                    self.stage = "cooldown"
                    self.cooldown_left = config.ZONE_ASSISTANT_COOLDOWN_BARS
                    out.append(ZoneAlert(BROKEN, symbol, label, zone, {"close": c}))
                elif c < zone.bottom:
                    self.stage = "idle"
                    out.append(ZoneAlert(RECLAIMED, symbol, label, zone, {"close": c, "wick": self.wick_extreme}))
        return out


# ------------------------------------------------------------------ Day 3-style forward outcome

@dataclass
class OutcomeTracker:
    """Started on an "at zone" alert: does the zone hold (price moves
    HOLD_MOVE_ATR away) or break (BREAK_ATR through) first -- the Day 3 label
    -- plus the max favorable move toward the next zone and whether it was
    reached by end of day. One instance per alert; call ``step`` on each
    closed 5m bar until it returns a result (not None) or the day ends.
    """
    direction: str                  # "long" or "short", from the at-zone alert
    zone: Zone
    next_zone: Zone | None           # the opposing zone to measure progress toward, if any
    resolved: bool = False
    outcome: str | None = None       # "held" | "broke" | None (unresolved by EOD)
    max_move_atr: float = 0.0
    reached_next: bool = False

    def step(self, bar: dict, atr: float, hhmm: str) -> dict | None:
        if self.resolved:
            return None
        long = self.direction == "long"
        near, far = (zone_edges(self.zone, long))
        hold_lvl = near + config.HOLD_MOVE_ATR * atr if long else near - config.HOLD_MOVE_ATR * atr
        break_lvl = far - config.BREAK_ATR * atr if long else far + config.BREAK_ATR * atr
        move = (bar["high"] - near) / atr if long else (near - bar["low"]) / atr
        self.max_move_atr = max(self.max_move_atr, move)
        if self.next_zone is not None:
            target = self.next_zone.bottom if long else self.next_zone.top
            reached = bar["high"] >= target if long else bar["low"] <= target
            self.reached_next = self.reached_next or reached
        broke = bar["low"] <= break_lvl if long else bar["high"] >= break_lvl
        held = bar["high"] >= hold_lvl if long else bar["low"] <= hold_lvl
        if broke:
            self.outcome, self.resolved = "broke", True
        elif held:
            self.outcome, self.resolved = "held", True
        elif hhmm >= config.EOD_EXIT:
            self.resolved = True
        if self.resolved:
            return {"outcome": self.outcome, "max_move_atr": self.max_move_atr, "reached_next": self.reached_next}
        return None


def zone_edges(zone: Zone, long: bool) -> tuple[float, float]:
    """(near edge, far edge) for the touch direction."""
    return (zone.top, zone.bottom) if long else (zone.bottom, zone.top)
