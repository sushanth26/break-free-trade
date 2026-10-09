"""Live bars.

``PollingSource`` (default): shortly after each 5m boundary, fetch the latest
few bars per symbol and return the newly closed ones. ``BarBuilder`` turns
ticks into 5m bars for the Webull MQTT stream (``WebullTickStream``), whose
message fields are parsed tolerantly like the HTTP bars.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import config
from data.base import normalize_bars, timeframe_delta


class BarBuilder:
    """Aggregate (time, price, size) ticks into bars of ``tf``; bars are emitted once closed."""

    def __init__(self, tf: str = "5m"):
        self.step = timeframe_delta(tf)
        self.cur: dict | None = None

    def _start(self, t: pd.Timestamp) -> pd.Timestamp:
        return t.floor(self.step)

    def on_tick(self, t: pd.Timestamp, price: float, size: float) -> list[pd.Series]:
        out = self.flush(t)
        start = self._start(t)
        if self.cur is None:
            self.cur = {"time": start, "open": price, "high": price, "low": price, "close": price, "volume": 0.0}
        c = self.cur
        c["high"], c["low"], c["close"] = max(c["high"], price), min(c["low"], price), price
        c["volume"] += size
        return out

    def flush(self, now: pd.Timestamp) -> list[pd.Series]:
        """Close the current bar if ``now`` is at/after its end."""
        if self.cur is not None and now >= self.cur["time"] + self.step:
            bar = pd.Series({k: self.cur[k] for k in ("open", "high", "low", "close", "volume")},
                            name=self.cur["time"])
            self.cur = None
            return [bar]
        return []


class PollingSource:
    """New closed 5m bars per symbol from a provider's recent-bars call."""

    def __init__(self, provider, symbols: list[str], count: int = 6, workers: int = 8):
        self.provider = provider
        self.symbols = symbols
        self.count = count
        self.last: dict[str, pd.Timestamp] = {}
        self.pool = ThreadPoolExecutor(max_workers=workers)

    def _fetch(self, sym: str) -> pd.DataFrame:
        try:
            return self.provider.get_bars(sym, "5m", count=self.count)
        except TypeError:
            return self.provider.get_bars(sym, "5m")

    def poll(self, now: pd.Timestamp) -> dict[str, pd.DataFrame]:
        out = {}
        for sym, bars in zip(self.symbols, self.pool.map(self._fetch, self.symbols)):
            bars = normalize_bars(bars)
            closed = bars[bars.index + pd.Timedelta("5min") <= now]
            if sym in self.last:
                closed = closed[closed.index > self.last[sym]]
            if len(closed):
                self.last[sym] = closed.index[-1]
                out[sym] = closed
        return out


def _tick_fields(msg) -> tuple[pd.Timestamp, float, float] | None:
    """Pull (time, price, size) from a decoded Webull tick, whatever its shape."""
    def get(obj, *names):
        for n in names:
            v = obj.get(n) if isinstance(obj, dict) else getattr(obj, n, None)
            if v not in (None, ""):
                return v
        return None
    t = get(msg, "time", "timestamp", "trade_time", "tradeTime")
    p = get(msg, "price", "trade_price", "tradePrice", "last")
    v = get(msg, "volume", "size", "trade_volume", "tradeVolume") or 0
    if t is None or p is None:
        return None
    t = pd.to_datetime(int(t), unit="ms", utc=True) if str(t).isdigit() else pd.Timestamp(t)
    return t.tz_convert(config.TZ), float(p), float(v)


class WebullTickStream:
    """MQTT tick stream → 5m bars per symbol (verify field names on first run)."""

    def __init__(self, symbols: list[str], on_bar, app_key=None, app_secret=None, region=None):
        import os
        import uuid
        from webull.data.data_streaming_client import DataStreamingClient

        self.builders = {s: BarBuilder() for s in symbols}
        self.on_bar = on_bar
        self.client = DataStreamingClient(app_key or os.environ["WEBULL_APP_KEY"],
                                          app_secret or os.environ["WEBULL_APP_SECRET"],
                                          region or os.environ.get("WEBULL_REGION", "us"), uuid.uuid4().hex)
        self.client.on_connect_success = lambda c, api, sid: c.subscribe(symbols, "US_STOCK", ["TICK"])
        self.client.on_quotes_message = self._on_message

    def _on_message(self, client, topic, msg):
        sym = next((s for s in self.builders if s in str(topic)), None)
        f = _tick_fields(msg)
        if sym and f:
            for bar in self.builders[sym].on_tick(*f):
                self.on_bar(sym, bar)

    def start(self):
        self.client.connect_and_loop_start()

    def stop(self):
        self.client.unsubscribe(unsubscribe_all=True)
