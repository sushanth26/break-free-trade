"""Print a StockProfile from cached history.

  python scripts/run_profile.py DELL --as-of "2026-10-09 10:00"
"""
import argparse

import _setup  # noqa: F401

import pandas as pd

import config
from data.csv_provider import CsvProvider
from engine.profile import build_profile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--as-of", default=None, help="ET time; default = after the last cached bar")
    ap.add_argument("--provider", default="alpaca")
    args = ap.parse_args()

    src = CsvProvider(config.CACHE_DIR, cache_provider=args.provider)
    bars5, daily = src.get_bars(args.symbol, "5m"), src.get_bars(args.symbol, "D")
    as_of = pd.Timestamp(args.as_of, tz=config.TZ) if args.as_of else bars5.index[-1] + pd.Timedelta("5min")
    p = build_profile(args.symbol, bars5, daily, as_of)
    print(f"{p.symbol} @ {p.as_of:%Y-%m-%d %H:%M}")
    print(f"  last      {p.last_price:.2f}")
    print(f"  5m ATR    {p.atr_5m:.2f}")
    print(f"  daily ATR {p.daily_atr:.2f}")
    print(f"  round     {p.round_step:.2f}")


if __name__ == "__main__":
    main()
