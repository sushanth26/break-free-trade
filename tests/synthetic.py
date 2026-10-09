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


def scripted_bounce_bars(warmup_days: int = 5, seed: int = 0) -> pd.DataFrame:
    """Random warm-up days, then a day that declines into 99.5-100.0, rejects it
    with a long lower wick on high volume, fills at the rejection close and rallies."""
    warm = random_bars(days=warmup_days, start_price=101.0, seed=seed)
    idx = session_index(warmup_days + 1)[-78:]
    rows = []
    price = 101.0
    for k in range(78):
        t = idx[k]
        if k < 6:                                   # 09:30-09:55 drift
            o, c = price, price + (0.02 if k % 2 else -0.02)
            rows.append((o, max(o, c) + 0.05, min(o, c) - 0.05, c, 5000.0))
        elif k < 10:                                # decline toward the zone
            o, c = price, price - 0.18
            rows.append((o, o + 0.03, c - 0.03, c, 6000.0))
        elif k == 10:                               # touch + rejection
            o = price
            rows.append((o, o + 0.02, 99.6, 100.08, 20000.0))
            c = 100.08
        elif k == 11:                               # fill bar: dips to 100.0, closes above zone
            o, c = 100.1, 100.3
            rows.append((o, 100.35, 100.0, c, 9000.0))
        elif k < 20:                                # rally through T1 (~101.96)
            o, c = price, price + 0.25
            rows.append((o, c + 0.05, o - 0.02, c, 8000.0))
        else:                                       # quiet afternoon
            o, c = price, price + (0.03 if k % 2 else -0.03)
            rows.append((o, max(o, c) + 0.04, min(o, c) - 0.04, c, 5000.0))
        price = rows[-1][3]
    day = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    return normalize_bars(pd.concat([warm, day]))
