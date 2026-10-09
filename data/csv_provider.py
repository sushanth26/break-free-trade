"""Local bars: daily Webull CSV archive and the Parquet history cache.

Layouts:
  archive/<SYMBOL>/<tf>/<YYYY-MM-DD>.csv   one file per trading day (archive_webull.py)
  cache/<provider>/<SYMBOL>_<tf>.parquet   downloaded history (download_history.py)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import config
from data.base import BarProvider, clip, normalize_bars


def write_day_csv(bars: pd.DataFrame, symbol: str, tf: str, root: str | Path = config.ARCHIVE_DIR) -> list[Path]:
    """Write bars to one CSV per trading day; existing days are merged, not lost."""
    bars = normalize_bars(bars)
    written = []
    for day, chunk in bars.groupby(bars.index.date):
        path = Path(root) / symbol.upper() / tf / f"{day}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            chunk = normalize_bars(pd.concat([read_csv_bars(path), chunk]))
        chunk.to_csv(path, index_label="time")
        written.append(path)
    return written


def read_csv_bars(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col="time")
    df.index = pd.to_datetime(df.index, utc=True)
    return normalize_bars(df)


def cache_path(provider: str, symbol: str, tf: str, root: str | Path = config.CACHE_DIR) -> Path:
    return Path(root) / provider / f"{symbol.upper()}_{tf}.parquet"


def write_cache(bars: pd.DataFrame, provider: str, symbol: str, tf: str,
                root: str | Path = config.CACHE_DIR) -> Path:
    path = cache_path(provider, symbol, tf, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalize_bars(bars).to_parquet(path)
    return path


class CsvProvider(BarProvider):
    """Reads the daily CSV archive, or a Parquet cache when ``cache_provider`` is set."""

    name = "csv"

    def __init__(self, root: str | Path = config.ARCHIVE_DIR, cache_provider: str | None = None):
        self.root = Path(root)
        self.cache_provider = cache_provider

    def get_bars(self, symbol, tf, start=None, end=None):
        if self.cache_provider:
            path = cache_path(self.cache_provider, symbol, tf, self.root)
            bars = normalize_bars(pd.read_parquet(path)) if path.exists() else normalize_bars(None)
        else:
            files = sorted((self.root / symbol.upper() / tf).glob("*.csv"))
            bars = normalize_bars(pd.concat([read_csv_bars(f) for f in files])) if files else normalize_bars(None)
        return clip(bars, start, end)
