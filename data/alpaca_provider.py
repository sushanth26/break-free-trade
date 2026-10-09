"""Alpaca historical bars: 12+ months of 1m-daily bars for backtests.

Requests unadjusted (raw) prices from the SIP feed so minute bars match
Webull. Alpaca stamps bars with their START time, our convention.
"""
from __future__ import annotations

import os

import pandas as pd

import config
from data.base import BarProvider, normalize_bars, to_ts

_TF = {"1m": (1, "Minute"), "5m": (5, "Minute"), "15m": (15, "Minute"),
       "30m": (30, "Minute"), "1h": (1, "Hour"), "D": (1, "Day")}


class AlpacaProvider(BarProvider):
    name = "alpaca"

    def __init__(self, api_key: str | None = None, secret_key: str | None = None, feed: str = "sip"):
        from alpaca.data.historical import StockHistoricalDataClient

        self.client = StockHistoricalDataClient(
            api_key or os.environ["ALPACA_API_KEY"], secret_key or os.environ["ALPACA_SECRET_KEY"])
        self.feed = feed

    def get_bars(self, symbol, tf, start=None, end=None, count: int | None = None):
        """``count`` = only the latest bars (live polling); otherwise start..end (default 12 months)."""
        if count is not None and start is None:
            start = pd.Timestamp.now(tz=config.TZ) - pd.Timedelta(days=4)
            return self.get_bars(symbol, tf, start, end).iloc[-count:]
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        amount, unit = _TF[tf]
        start = to_ts(start if start is not None
                      else pd.Timestamp.now(tz=config.TZ) - pd.DateOffset(months=config.HISTORY_MONTHS))
        req = StockBarsRequest(
            symbol_or_symbols=symbol.upper(),
            timeframe=TimeFrame(amount, TimeFrameUnit[unit]),
            start=start.to_pydatetime(),
            end=to_ts(end).to_pydatetime() if end is not None else None,
            adjustment=Adjustment.RAW,
            feed=DataFeed(self.feed),
        )
        df = self.client.get_stock_bars(req).df
        if df.empty:
            return normalize_bars(None)
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol.upper(), level="symbol")
        bars = normalize_bars(df)
        if tf == "D":
            bars.index = bars.index.normalize()
        return bars
