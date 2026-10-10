"""Simple bounce — a separate, deliberately plain strategy the trader wants tested
on its own, alongside (not instead of) the main engine.

Long at a support zone (short at resistance is the exact mirror):
  touch   price trades into the zone: a bar's low reaches the zone top or below
  entry   the first 5m close back above the zone top, within SIMPLE_MAX_BARS_TO_ENTRY
          bars of the touch (touch bar counts as the first). Entry = that close.
  stop    the lowest low across every bar from the touch through the entry bar,
          minus SIMPLE_STOP_BUFFER_ATR * atr
  break   a close more than SIMPLE_BREAK_ATR below the zone bottom, before entry,
          cancels the setup
  expire  no entry within the bar budget cancels the setup unfilled

No grades, no regime, no news, no multi-stage confirmation -- one touch, one
entry rule, one stop, one target. The target (next opposing zone) and the
minimum R check need the full zone list, so they are computed by
``plan_simple_trade`` once a touch tracker reports an entry, not inside the
tracker itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config
from engine.zones import Zone

IDLE, TOUCH, ENTRY, FAIL = "idle", "touch", "entry", "fail"


@dataclass
class SimpleUpdate:
    stage: str
    prev_stage: str
    direction: str             # "long" (support) or "short" (resistance)
    zone: Zone
    entry_price: float = float("nan")
    stop: float = float("nan")
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.stage != self.prev_stage


@dataclass
class SimpleBounceTracker:
    """One instance per zone per direction. Call ``step`` on every closed 5m bar."""
    zone: Zone
    direction: str
    stage: str = IDLE
    lowest_low: float = float("nan")    # in "long space" (shorts mirrored); the running stop basis
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

    def step(self, bar: dict, atr: float) -> SimpleUpdate:
        """Advance on one closed 5m bar (dict with open/high/low/close/volume)."""
        prev = self.stage
        if self.stage in (ENTRY, FAIL):
            self.stage = IDLE
        o, h, l, c = self._m(bar)
        near, far = self._edges()
        reason = ""

        if self.stage == IDLE and l <= near:
            self.stage, self.bars_since, self.lowest_low = TOUCH, 0, l

        if self.stage == TOUCH:
            if self.stage != prev:
                pass  # just entered TOUCH this bar; lowest_low already seeded above
            else:
                self.bars_since += 1
                self.lowest_low = min(self.lowest_low, l)

            if c < far - config.SIMPLE_BREAK_ATR * atr:
                self.stage, reason = FAIL, "broke zone"
            elif c > near:
                self.stage = ENTRY
            elif self.bars_since >= config.SIMPLE_MAX_BARS_TO_ENTRY:
                self.stage, reason = FAIL, "no entry within bar budget"

        entry_price, stop = float("nan"), float("nan")
        if self.stage == ENTRY:
            entry_price = c
            stop = self.lowest_low - config.SIMPLE_STOP_BUFFER_ATR * atr
            entry_price, stop = self._unmirror(entry_price), self._unmirror(stop)
        return SimpleUpdate(self.stage, prev, self.direction, self.zone, entry_price, stop, reason)

    def _unmirror(self, x: float) -> float:
        return x * self._sign


def plan_simple_trade(update: SimpleUpdate, zones: list[Zone], atr: float,
                      min_t1_r: float = config.SIMPLE_MIN_T1_R) -> tuple[dict | None, str]:
    """Target = the next opposing zone's near edge, minus/plus SIMPLE_STOP_BUFFER_ATR * atr.

    Skip (None, reason) if there is no opposing zone or the reward is under min_t1_r R.
    """
    if update.stage != ENTRY:
        return None, "not an entry"
    long = update.direction == "long"
    entry, stop = update.entry_price, update.stop
    risk = entry - stop if long else stop - entry
    if risk <= 0:
        return None, "non-positive risk"
    opposing = [z for z in zones if (z.bottom > update.zone.top if long else z.top < update.zone.bottom)]
    if not opposing:
        return None, "no opposing zone"
    nearest = min(opposing, key=lambda z: z.bottom if long else z.top) if long else \
        max(opposing, key=lambda z: z.top)
    target = nearest.bottom - config.SIMPLE_STOP_BUFFER_ATR * atr if long else \
        nearest.top + config.SIMPLE_STOP_BUFFER_ATR * atr
    reward = target - entry if long else entry - target
    r = reward / risk
    if r < min_t1_r:
        return None, f"target {r:.2f}R < {min_t1_r:g}R"
    return {"entry": entry, "stop": stop, "target": target, "r_to_target": r, "zone": update.zone,
           "target_zone": nearest}, ""
