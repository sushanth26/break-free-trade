"""Zones for live: the same build as the backtest, recomputed on a recent window.

The window covers every bar the latest zone set can depend on (range bars,
loopback and pivot confirmation), so live zones equal backtest zones.
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from backtest.zone_backtest import build_timeline
from data.base import regular_hours
from engine.settings import EngineSettings

_BARS_PER = {"5m": 1, "15m": 3, "30m": 6, "1h": 12, "D": 78}


class LiveZoneSource:
    def __init__(self, symbol: str, settings: EngineSettings):
        self.symbol = symbol
        self.settings = settings
        self.timeline = None

    def window_bars(self) -> int:
        z = self.settings.zone
        need = max(z.range_bars, z.loopback + 2 * z.pivot_period + 1) + 2
        tfs = [tf for tf in self.settings.timeframes if tf != "D"]
        return need * max(_BARS_PER[tf] for tf in tfs) + 78 if tfs else 78

    def update(self, bars5: pd.DataFrame, daily: pd.DataFrame | None = None):
        reg = regular_hours(bars5).iloc[-self.window_bars():]
        data = SimpleNamespace(symbol=self.symbol, bars=reg, daily=daily)
        self.timeline = build_timeline(data, self.settings.timeframes, self.settings.zone, cache={})

    def __call__(self, now: pd.Timestamp):
        return self.timeline(now) if self.timeline is not None else []
