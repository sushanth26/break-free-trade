"""Trade plan and position management — the trade rules from the plan.

Shared by the backtest (simulated fills) and live (paper tracking of the
alerted trade). Fills come from an injected fill model, so this module has
no backtest-only shortcuts. Every distance is a multiple of 5m ATR.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

import config
from engine.profile import round_levels
from engine.zones import Zone


@dataclass
class TradePlan:
    symbol: str
    direction: str              # "long" | "short"
    entry: float
    stop: float
    t1: float
    t2: float
    shares: int
    zone: Zone
    signal_time: pd.Timestamp   # bar close the alert fires on
    atr: float
    grade: str = ""
    aplus: int = 0
    zone_score: float = float("nan")
    regime: str = ""
    premarket: bool = False
    notes: dict = field(default_factory=dict)

    @property
    def sign(self) -> int:
        return 1 if self.direction == "long" else -1

    @property
    def risk_per_share(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def r_to_t1(self) -> float:
        return abs(self.t1 - self.entry) / self.risk_per_share if self.risk_per_share else 0.0


def plan_trade(symbol: str, direction: str, entry: float, rej_low: float, rej_high: float, zone: Zone,
               zones: list[Zone], atr: float, round_step: float, signal_time: pd.Timestamp,
               risk_dollars: float = config.RISK_PER_TRADE, size_mult: float = 1.0,
               min_t1_r: float = config.MIN_T1_R) -> tuple[TradePlan | None, str]:
    """Build entry/stop/T1/T2/size, or (None, reason) if the trade must be skipped."""
    s = 1 if direction == "long" else -1
    stop = rej_low - config.STOP_BUFFER_ATR * atr if s == 1 else rej_high + config.STOP_BUFFER_ATR * atr
    risk = (entry - stop) * s
    if not risk > 0:
        return None, "no room for a stop"
    front = config.FRONT_RUN_ATR * atr
    # opposing zones beyond the entry, nearest first
    if s == 1:
        opp = sorted((z.bottom for z in zones if z is not zone and z.bottom > entry))
    else:
        opp = sorted((z.top for z in zones if z is not zone and z.top < entry), reverse=True)
    t1 = opp[0] - s * front if opp else entry + s * config.DEFAULT_T1_R * risk
    r_t1 = (t1 - entry) * s / risk
    if r_t1 > config.MAX_FIRST_ZONE_R:
        return None, f"first zone {r_t1:.1f}R away"
    if r_t1 < min_t1_r:
        return None, f"T1 only {r_t1:.1f}R away"
    beyond = [x for x in round_levels(t1, round_step, n=3) if (x - t1) * s > front]
    nxt_round = min(beyond, key=lambda x: abs(x - t1)) if beyond else t1 + s * risk
    candidates = [nxt_round] + ([opp[1]] if len(opp) > 1 else [])
    t2 = min(candidates, key=lambda x: abs(x - t1)) - s * front
    if (t2 - t1) * s <= 0:
        t2 = t1 + s * risk
    shares = int(math.floor(risk_dollars * size_mult / risk))
    if shares < 1:
        return None, "size below 1 share"
    return TradePlan(symbol, direction, round(entry, 2), round(stop, 2), round(t1, 2), round(t2, 2), shares,
                     zone, signal_time, atr), ""


@dataclass
class Action:
    time: pd.Timestamp
    kind: str          # filled, cancelled, target1, target2, warning, stop, exit
    price: float = float("nan")
    shares: int = 0
    reason: str = ""
    new_stop: float = float("nan")


class Position:
    """One alerted trade from pending entry to flat. Call ``on_bar`` once per closed 5m bar."""

    def __init__(self, plan: TradePlan, fills):
        self.plan = plan
        self.fills = fills
        self.state = "pending"            # pending → open → closed / cancelled
        self.bars_waiting = 0
        self.entry_fill = float("nan")
        self.touched_only = False
        self.shares_open = 0
        self.stop = plan.stop
        self.t1_hit = self.t2_hit = self.warned = False
        self.win: bool | None = None      # T1 before stop
        self.pnl = 0.0
        self.commission = 0.0
        self.stall = 0
        self.best = float("nan")          # best price since entry (long space)
        self.recent_lows: list[float] = []   # last two bar lows (long space) = last higher low
        self.fill_time = self.exit_time = None
        self.exit_reason = ""
        self.actions: list[Action] = []

    # ------------------------------------------------------------------ helpers
    def _sell(self, t, qty, price, kind, reason="", new_stop=float("nan")):
        s = self.plan.sign
        qty = min(qty, self.shares_open)
        if qty <= 0:
            return
        self.pnl += (price - self.entry_fill) * qty * s
        self.commission += self.fills.commission(qty)
        self.shares_open -= qty
        self.actions.append(Action(t, kind, price, qty, reason, new_stop))
        if self.shares_open == 0:
            self.state, self.exit_time, self.exit_reason = "closed", t, reason or kind

    def _exit_all(self, t, price, reason):
        if self.win is None:
            self.win = False
        self._sell(t, self.shares_open, price, "exit", reason)

    @property
    def r_multiple(self) -> float:
        risk = self.plan.risk_per_share * self.plan.shares
        return (self.pnl - self.commission) / risk if risk else 0.0

    # ------------------------------------------------------------------ bar update
    def on_bar(self, t: pd.Timestamp, bar: dict, row: pd.Series | None = None,
               news_against: bool = False) -> list[Action]:
        n0 = len(self.actions)
        p, s = self.plan, self.plan.sign
        if self.state == "pending":
            self.bars_waiting += 1
            fill = self.fills.entry_fill(p.direction, p.entry, bar)
            if fill is None:
                hit_stop = (bar["low"] <= p.stop) if s == 1 else (bar["high"] >= p.stop)
                hit_t1 = (bar["high"] >= p.t1) if s == 1 else (bar["low"] <= p.t1)
                if hit_stop or hit_t1 or self.bars_waiting >= config.ENTRY_FILL_BARS:
                    self.state = "cancelled"
                    reason = "invalidated" if hit_stop else "ran to T1 unfilled" if hit_t1 else "not filled"
                    self.actions.append(Action(t, "cancelled", reason=reason))
                return self.actions[n0:]
            price, self.touched_only = fill
            self.state, self.entry_fill, self.fill_time = "open", price, t
            self.shares_open = p.shares
            self.commission += self.fills.commission(p.shares)
            self.best = self.entry_fill * s
            self.actions.append(Action(t, "filled", price, p.shares))
            # same bar: only the stop can be judged (order of moves inside the bar is unknown)
            stop_px = self.fills.stop_fill(p.direction, self.stop, bar)
            if stop_px is not None:
                self.win = False
                self._sell(t, self.shares_open, stop_px, "stop", "stopped on entry bar")
            return self.actions[n0:]
        if self.state != "open":
            return []

        atr = p.atr
        # 1) stop first (conservative), then targets
        stop_px = self.fills.stop_fill(p.direction, self.stop, bar)
        if stop_px is not None:
            if self.win is None:
                self.win = False
            self._sell(t, self.shares_open, stop_px, "stop", "stop hit")
            return self.actions[n0:]
        third = max(p.shares // 3, 1)
        if not self.t1_hit and self.fills.target_fill(p.direction, p.t1, bar) is not None:
            self.t1_hit, self.win = True, True
            self.stop = self.entry_fill
            self._sell(t, third, self.fills.target_fill(p.direction, p.t1, bar), "target1", "T1 hit", self.stop)
        if self.t1_hit and not self.t2_hit and self.state == "open" and \
                self.fills.target_fill(p.direction, p.t2, bar) is not None:
            self.t2_hit = True
            if row is not None:
                cloud = row["cloud_slow_lo"] if s == 1 else row["cloud_slow_hi"]
                new = cloud - s * config.STOP_BUFFER_ATR * atr
                if (new - self.stop) * s > 0:
                    self.stop = new
            self._sell(t, third, self.fills.target_fill(p.direction, p.t2, bar), "target2", "T2 hit", self.stop)
        if self.state != "open":
            return self.actions[n0:]

        # 2) close-based rules
        c = bar["close"]
        hi_l = bar["high"] if s == 1 else -bar["low"]
        lo_l = bar["low"] if s == 1 else -bar["high"]
        if hi_l > self.best:
            self.best, self.stall = hi_l, 0
        elif bar["high"] - bar["low"] < config.STALL_RANGE_ATR * atr:
            self.stall += 1
        last_higher_low = min(self.recent_lows) if len(self.recent_lows) == 2 else -math.inf
        self.recent_lows = (self.recent_lows + [lo_l])[-2:]

        in_zone = (c < p.zone.top) if s == 1 else (c > p.zone.bottom)
        if news_against:
            self._exit_all(t, self.fills.market_fill(p.direction, c, selling=True), "news against")
        elif not self.t1_hit and in_zone:
            self._exit_all(t, self.fills.market_fill(p.direction, c, selling=True), "false bounce: closed back in zone")
        elif row is not None and self.t1_hit and ((c < row["cloud_slow_lo"]) if s == 1 else (c > row["cloud_slow_hi"])):
            self._exit_all(t, self.fills.market_fill(p.direction, c, selling=True), "closed beyond 34/50 cloud")
        elif row is not None and self.t2_hit and ((c < row["cloud_fast_lo"]) if s == 1 else (c > row["cloud_fast_hi"])):
            self._exit_all(t, self.fills.market_fill(p.direction, c, selling=True), "trail: closed beyond 5/12 cloud")
        elif self.t2_hit and c * s < last_higher_low:
            self._exit_all(t, self.fills.market_fill(p.direction, c, selling=True), "trail: below last higher low")
        elif t.strftime("%H:%M") >= config.EOD_EXIT:
            self._exit_all(t, self.fills.market_fill(p.direction, c, selling=True), "end of day")
        elif self.stall >= config.STALL_BARS and not self.warned:
            self.warned = True
            new = (bar["low"] if s == 1 else bar["high"]) - s * config.STOP_BUFFER_ATR * atr
            if (new - self.stop) * s > 0:
                self.stop = new
            self._sell(t, max(self.shares_open // 2, 1), self.fills.market_fill(p.direction, c, selling=True),
                       "warning", f"{config.STALL_BARS} stalling candles", self.stop)
        return self.actions[n0:]

    def record(self) -> dict:
        p = self.plan
        return {
            "symbol": p.symbol, "direction": p.direction, "signal_time": p.signal_time,
            "fill_time": self.fill_time, "exit_time": self.exit_time, "state": self.state,
            "entry": p.entry, "entry_fill": self.entry_fill, "stop": p.stop, "t1": p.t1, "t2": p.t2,
            "shares": p.shares, "r_to_t1": p.r_to_t1, "win": bool(self.win), "r": self.r_multiple,
            "pnl": self.pnl - self.commission, "exit_reason": self.exit_reason, "touched_only": self.touched_only,
            "grade": p.grade, "aplus": p.aplus, "zone_score": p.zone_score, "regime": p.regime,
            "premarket": p.premarket, "zone_bottom": p.zone.bottom, "zone_top": p.zone.top,
            "timeframes": "+".join(p.zone.timeframes), **p.notes,
        }
