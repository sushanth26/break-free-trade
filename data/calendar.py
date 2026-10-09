"""Economic and earnings calendars, stored as dated tables.

Economic calendar CSV (data/calendars/economic.csv): time,event,importance
  e.g. 2026-10-14 08:30,CPI,high   (times in America/New_York)
Earnings calendar CSV (data/calendars/earnings.csv): date,symbol,session
  e.g. 2026-10-28,META,amc
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import config
from data.base import to_ts

CAL_DIR = Path(__file__).parent / "calendars"


def load_economic(path: str | Path = CAL_DIR / "economic.csv") -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(config.TZ)
    return df.sort_values("time").reset_index(drop=True)


def load_earnings(path: str | Path = CAL_DIR / "earnings.csv") -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["symbol"] = df["symbol"].str.upper()
    return df


def in_news_window(t, economic: pd.DataFrame, window: tuple[int, int] = config.NEWS_WINDOW) -> bool:
    """True if ``t`` is inside [event + before, event + after] for any macro event."""
    t = to_ts(t)
    before, after = (pd.Timedelta(minutes=m) for m in window)
    return bool(((economic["time"] + before <= t) & (t <= economic["time"] + after)).any())


def is_earnings_week(symbol: str, t, earnings: pd.DataFrame) -> bool:
    """True if ``symbol`` reports in the same ISO week as ``t``."""
    week = to_ts(t).isocalendar()[:2]
    dates = earnings.loc[earnings["symbol"] == symbol.upper(), "date"]
    return any(pd.Timestamp(d).isocalendar()[:2] == week for d in dates)
