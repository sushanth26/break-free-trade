"""Webull OpenAPI bars (HTTP): recent bars at startup and the daily archive.

The history endpoint returns at most 1,200 recent bars with no date range.
Uses the data-only ``DataClient`` of webull-openapi-python-sdk v3 (package
``webull``); no trading client is ever created. Minute bars are unadjusted,
daily bars are adjusted by Webull. Response shapes may differ from the docs,
so the parser is tolerant of key names and nesting; verify on first run with
scripts/check_alignment.py.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

import pandas as pd

import config
from data.base import BarProvider, clip, normalize_bars, timeframe_delta

_TIMESPAN = {"1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30", "1h": "M60", "D": "D"}

_KEYS = {
    "time": ("time", "timestamp", "t", "trade_time", "tradeTime", "date"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c"),
    "volume": ("volume", "v", "vol"),
}


def _find_rows(payload: Any) -> list[dict]:
    """Locate the list of bar dicts anywhere inside a response."""
    if hasattr(payload, "json") and callable(payload.json):
        payload = payload.json()
    if isinstance(payload, list):
        if payload and isinstance(payload[0], dict) and any(k in payload[0] for k in _KEYS["close"]):
            return payload
        for item in payload:
            rows = _find_rows(item)
            if rows:
                return rows
        return []
    if isinstance(payload, dict):
        for value in payload.values():
            rows = _find_rows(value)
            if rows:
                return rows
    return []


def _pick(row: dict, field: str):
    for key in _KEYS[field]:
        if key in row:
            return row[key]
    raise KeyError(f"no {field} key in bar {sorted(row)}")


def _parse_time(values: Iterable) -> pd.DatetimeIndex:
    s = pd.Series(list(values))
    if pd.api.types.is_numeric_dtype(s):
        unit = "ms" if s.abs().max() > 1e11 else "s"
        return pd.DatetimeIndex(pd.to_datetime(s, unit=unit, utc=True))
    return pd.DatetimeIndex(pd.to_datetime(s, utc=True))


def parse_bars(payload: Any, time_shift: pd.Timedelta = pd.Timedelta(0)) -> pd.DataFrame:
    """Turn any Webull bars response into the standard schema.

    ``time_shift`` converts the provider's timestamp convention to bar START
    (e.g. -5min if Webull stamps 5m bars with their end time).
    """
    rows = _find_rows(payload)
    if not rows:
        return normalize_bars(None)
    df = pd.DataFrame({f: [_pick(r, f) for r in rows] for f in _KEYS if f != "time"})
    df.index = _parse_time(_pick(r, "time") for r in rows) + time_shift
    return normalize_bars(df.apply(pd.to_numeric))


SESSIONS = {"regular": ["RTH"], "extended": ["PRE", "RTH", "ATH"]}


class WebullProvider(BarProvider):
    name = "webull"

    def __init__(self, app_key: str | None = None, app_secret: str | None = None,
                 region: str | None = None, stamps_bar_end: bool = False, session: str = "extended"):
        from webull.core.client import ApiClient
        from webull.data.data_client import DataClient

        client = ApiClient(app_key or os.environ["WEBULL_APP_KEY"],
                           app_secret or os.environ["WEBULL_APP_SECRET"],
                           region or os.environ.get("WEBULL_REGION", "us"))
        self.market_data = DataClient(client).market_data
        self.stamps_bar_end = stamps_bar_end
        self.sessions = SESSIONS[session]

    def get_bars(self, symbol, tf, start=None, end=None, count: int = config.WEBULL_MAX_BARS):
        res = self.market_data.get_batch_history_bar(
            [symbol.upper()], "US_STOCK", _TIMESPAN[tf], count=str(count),
            trading_sessions=self.sessions)
        status = getattr(res, "status_code", 200)
        if status == 403:
            raise PermissionError("Webull 403: market data subscription not active for this app key")
        if status != 200:
            raise RuntimeError(f"Webull history error {status}: {getattr(res, 'text', res)}")
        shift = -timeframe_delta(tf) if self.stamps_bar_end and tf != "D" else pd.Timedelta(0)
        bars = parse_bars(res, shift)
        if tf == "D":
            bars.index = bars.index.normalize()
        return clip(bars, start, end)
