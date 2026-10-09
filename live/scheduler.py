"""Daily schedule (ET): connect 4:00, premarket plan 8:30, cutoff reminder 15:45,
archive 16:05, shutdown 20:00. Pure functions so they can be tested."""
from __future__ import annotations

import pandas as pd

import config


def jobs_due(now: pd.Timestamp, done: set[str], schedule: dict[str, str] = config.SCHEDULE) -> list[str]:
    """Jobs whose time has come today and that have not run yet (in time order)."""
    hhmm = now.strftime("%H:%M")
    return [j for j, t in sorted(schedule.items(), key=lambda kv: kv[1]) if hhmm >= t and j not in done]


def next_bar_close(now: pd.Timestamp) -> pd.Timestamp:
    """The next 5-minute boundary after ``now``."""
    return now.floor("5min") + pd.Timedelta("5min")


def is_trading_day(day: pd.Timestamp) -> bool:
    return day.weekday() < 5
