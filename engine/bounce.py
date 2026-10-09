"""Module 7 — real vs false bounce, per zone: Touch → Rejection → Confirmed / Fail.

Long at support (short at resistance is the mirror):
  touch      low reaches the zone top after the prior close was above it
  rejection  lower wick >= REJECTION_WICK_PCT of the candle and the close is
             REJECTION_CLOSE_ATR above the zone top (can be the touch bar)
  confirmed  within FOLLOW_THROUGH_BARS: close above the rejection candle's
             high, at least FOLLOW_THROUGH_ATR above the rejection close, on
             volume >= average, and the rejection low (higher low) holds
  fail       close back inside the zone, rejection low lost, or no follow-through
Entry price: confirmed mode = the rejection candle's high (the "higher high"
break, worked as a limit after the alert); early mode = the rejection close.
Entry is refused when that price is already MAX_ENTRY_DIST_ATR past the zone edge.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config
from engine.zones import Zone

IDLE, TOUCH, REJECTION, CONFIRMED, FAIL = "idle", "touch", "rejection", "confirmed", "fail"


@dataclass
class BounceUpdate:
    stage: str
    prev_stage: str
    direction: str            # "long" (support) or "short" (resistance)
    zone: Zone
    rej_high: float = float("nan")
    rej_low: float = float("nan")
    entry_ok: bool = False
    entry_price: float = float("nan")
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.stage != self.prev_stage


@dataclass
class BounceTracker:
    zone: Zone
    direction: str
    stage: str = IDLE
    rej_high: float = float("nan")      # in "long space" (shorts are mirrored)
    rej_low: float = float("nan")
    rej_close: float = float("nan")
    bars_since: int = 0
    _sign: int = field(init=False)

    def __post_init__(self):
        self._sign = 1 if self.direction == "long" else -1

    def _m(self, bar: dict) -> tuple[float, float, float, float]:
        """Bar in long space: shorts are flipped so the same rules apply."""
        if self._sign == 1:
            return bar["open"], bar["high"], bar["low"], bar["close"]
        return -bar["open"], -bar["low"], -bar["high"], -bar["close"]

    def _edges(self) -> tuple[float, float]:
        """(near edge, far edge) in long space."""
        z = self.zone
        return (z.top, z.bottom) if self._sign == 1 else (-z.bottom, -z.top)

    def _unmirror(self, x: float) -> float:
        return x * self._sign

    def step(self, bar: dict, prev_close: float, atr: float, vol_avg: float) -> BounceUpdate:
        """Advance on one closed 5m bar (dict with open/high/low/close/volume)."""
        prev = self.stage
        if self.stage in (CONFIRMED, FAIL):
            self.stage = IDLE
        o, h, l, c = self._m(bar)
        pc = prev_close * self._sign
        near, far = self._edges()
        reason = ""

        if self.stage == IDLE and pc > near and l <= near:
            self.stage = TOUCH
        if self.stage == TOUCH:
            rng = h - l
            wick = min(o, c) - l
            if rng > 0 and wick >= config.REJECTION_WICK_PCT * rng and c >= near + config.REJECTION_CLOSE_ATR * atr:
                self.stage, self.bars_since = REJECTION, 0
                self.rej_high, self.rej_low, self.rej_close = h, l, c
            elif c < far - config.BREAK_ATR * atr:
                self.stage, reason = FAIL, "broke zone"
            elif c > near + config.MAX_ENTRY_DIST_ATR * atr:
                self.stage, reason = IDLE, "left without rejection"
        elif self.stage == REJECTION:
            self.bars_since += 1
            if c < near:
                self.stage, reason = FAIL, "false bounce: closed back in zone"
            elif l < self.rej_low:
                self.stage, reason = FAIL, "higher low lost"
            elif (c > self.rej_high and h - self.rej_close >= config.FOLLOW_THROUGH_ATR * atr
                  and bar["volume"] >= vol_avg):
                self.stage = CONFIRMED
            elif self.bars_since >= config.FOLLOW_THROUGH_BARS:
                self.stage, reason = FAIL, "no follow-through"

        entry_ok, entry = False, float("nan")
        if self.stage == CONFIRMED or (self.stage == REJECTION and self.bars_since == 0):
            entry = self.rej_high if self.stage == CONFIRMED else self.rej_close
            entry_ok = entry <= near + config.MAX_ENTRY_DIST_ATR * atr
            if not entry_ok:
                reason = "chasing: entry past MAX_ENTRY_DIST_ATR"
            entry = self._unmirror(entry)
        hi, lo = (self.rej_high, self.rej_low) if self._sign == 1 else (-self.rej_low, -self.rej_high)
        return BounceUpdate(self.stage, prev, self.direction, self.zone, hi, lo, entry_ok, entry, reason)
