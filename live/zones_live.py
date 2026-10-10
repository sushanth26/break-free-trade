"""Zones for live: the same build as the backtest, recomputed on a recent window.

The window covers every bar the latest zone set can depend on (range bars,
loopback and pivot confirmation), so live zones equal backtest zones.
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from backtest.zone_backtest import build_timeline
from engine.settings import EngineSettings

_BARS_PER = {"5m": 1, "15m": 3, "30m": 6, "1h": 12, "D": 78}


class LiveZoneSource:
    def __init__(self, symbol: str, settings: EngineSettings, session: str = "regular"):
        self.symbol = symbol
        self.settings = settings
        self.session = session
        self.timeline = None

    def window_bars(self) -> int:
        z = self.settings.zone
        need = max(z.range_bars, z.loopback + 2 * z.pivot_period + 1) + 2
        tfs = [tf for tf in self.settings.timeframes if tf != "D"]
        per_day = 78 if self.session == "regular" else 192   # 09:30-16:00 vs 04:00-20:00
        return need * max(_BARS_PER[tf] for tf in tfs) + per_day if tfs else per_day

    def update(self, bars5: pd.DataFrame, daily: pd.DataFrame | None = None):
        # don't pre-filter to regular hours here: build_timeline applies the session filter itself,
        # and for session="extended" the extended-hours bars must still be present to filter down to.
        win = bars5.iloc[-self.window_bars():]
        data = SimpleNamespace(symbol=self.symbol, bars=win, daily=daily)
        self.timeline = build_timeline(data, self.settings.timeframes, self.settings.zone, cache={},
                                       session=self.session)

    def __call__(self, now: pd.Timestamp):
        return self.timeline(now) if self.timeline is not None else []
