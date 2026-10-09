"""Honest fills.

- Entry limit: fills when price reaches the limit (``low <= limit`` for a long).
  With ``adverse_selection=True`` it must trade THROUGH by a tick, so entries
  price only touched (often the cleanest bounces) are not filled.
- Targets (limit exits) always need a trade-through by a tick:
  T1 at 582.00 with a high of 581.91 (or 582.00) is no fill.
- Stops fill at the stop, or the open if the bar gaps through it.
- Every fill pays SLIPPAGE_PCT of price against us; commission per share.
"""
from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass(frozen=True)
class FillModel:
    slippage_pct: float = config.SLIPPAGE_PCT
    commission_per_share: float = config.COMMISSION_PER_SHARE
    tick: float = config.TICK_SIZE
    adverse_selection: bool = False

    def _slip(self, price: float, buying: bool) -> float:
        k = self.slippage_pct / 100
        return price * (1 + k) if buying else price * (1 - k)

    def commission(self, shares: int) -> float:
        return shares * self.commission_per_share

    def entry_fill(self, direction: str, limit: float, bar: dict) -> tuple[float, bool] | None:
        """(fill price, touched_only) or None. Long = buy limit, short = sell limit."""
        long = direction == "long"
        reach = bar["low"] if long else bar["high"]
        touched = reach <= limit if long else reach >= limit
        through = reach <= limit - self.tick if long else reach >= limit + self.tick
        if not touched or (self.adverse_selection and not through):
            return None
        gapped = bar["open"] < limit if long else bar["open"] > limit
        price = bar["open"] if gapped else limit
        return self._slip(price, buying=long), not through

    def target_fill(self, direction: str, target: float, bar: dict) -> float | None:
        long = direction == "long"
        through = bar["high"] >= target + self.tick if long else bar["low"] <= target - self.tick
        if not through:
            return None
        gapped = bar["open"] > target if long else bar["open"] < target
        return self._slip(bar["open"] if gapped else target, buying=not long)

    def stop_fill(self, direction: str, stop: float, bar: dict) -> float | None:
        long = direction == "long"
        hit = bar["low"] <= stop if long else bar["high"] >= stop
        if not hit:
            return None
        gapped = bar["open"] < stop if long else bar["open"] > stop
        return self._slip(bar["open"] if gapped else stop, buying=not long)

    def market_fill(self, direction: str, price: float, selling: bool) -> float:
        """Exit at a bar close. ``selling`` means closing the position."""
        long = direction == "long"
        buying = (not long) if selling else long
        return self._slip(price, buying=buying)
