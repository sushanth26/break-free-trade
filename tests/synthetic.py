"""Synthetic bars for tests: deterministic random walks in the standard schema."""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from data.base import normalize_bars


def session_index(days: int, start: str = "2026-03-02", extended: bool = False,
                  freq: str = "5min") -> pd.DatetimeIndex:
    """Bar-start times for ``days`` weekdays (regular session, or 04:00-20:00)."""
    open_t, close_t = ("04:00", "20:00") if extended else (config.REGULAR_OPEN, config.REGULAR_CLOSE)
    dates = pd.bdate_range(start, periods=days)
    parts = [pd.date_range(f"{d.date()} {open_t}", f"{d.date()} {close_t}", freq=freq,
                           inclusive="left", tz=config.TZ) for d in dates]
    return parts[0].append(parts[1:]) if len(parts) > 1 else parts[0]


def random_bars(days: int = 30, start_price: float = 100.0, seed: int = 0,
                extended: bool = False, freq: str = "5min", gap_pct: float = 0.0) -> pd.DataFrame:
    """Random-walk OHLCV bars; ``gap_pct`` adds an overnight gap at each new day."""
    rng = np.random.default_rng(seed)
    idx = session_index(days, extended=extended, freq=freq)
    steps = rng.normal(0, 0.002, len(idx))
    new_day = np.r_[False, idx.normalize()[1:] != idx.normalize()[:-1]]
    steps[new_day] += gap_pct / 100
    close = start_price * np.exp(np.cumsum(steps))
    open_ = np.r_[start_price, close[:-1]]
    open_[new_day] = close[np.flatnonzero(new_day) - 1] * (1 + gap_pct / 100)
    spread = np.abs(rng.normal(0, 0.0015, len(idx))) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    vol = rng.integers(1_000, 10_000, len(idx)).astype(float)
    return normalize_bars(pd.DataFrame({"open": open_, "high": high, "low": low,
                                        "close": close, "volume": vol}, index=idx))


def daily_from(bars: pd.DataFrame) -> pd.DataFrame:
    from data.base import resample
    return resample(bars, "D")
