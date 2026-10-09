"""Download 12 months of bars (+ news) from Alpaca into the Parquet cache.

  python scripts/download_history.py                       # all universe symbols, 5m + D + news
  python scripts/download_history.py --symbols DELL NVDA --timeframes 5m 1m
"""
import argparse

import _setup  # noqa: F401

import pandas as pd

import config
from data.alpaca_provider import AlpacaProvider
from data.csv_provider import write_cache
from data.news import fetch_alpaca_news

UNIVERSE = sorted(set(config.BUILD_STOCKS + config.VALIDATION_STOCKS + config.CONTEXT_SYMBOLS))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=UNIVERSE)
    ap.add_argument("--timeframes", nargs="+", default=["5m", "D"])
    ap.add_argument("--months", type=int, default=config.HISTORY_MONTHS)
    ap.add_argument("--no-news", action="store_true")
    args = ap.parse_args()

    end = pd.Timestamp.now(tz=config.TZ).normalize()
    start = end - pd.DateOffset(months=args.months)
    provider = AlpacaProvider()
    print(f"{'symbol':<6} {'tf':<3} {'bars':>7}  first → last")
    for sym in args.symbols:
        for tf in args.timeframes:
            bars = provider.get_bars(sym, tf, start, end)
            write_cache(bars, "alpaca", sym, tf)
            span = f"{bars.index[0]} → {bars.index[-1]}" if len(bars) else "no data"
            print(f"{sym:<6} {tf:<3} {len(bars):>7}  {span}")

    if not args.no_news:
        news = fetch_alpaca_news(args.symbols, start, end)
        path = f"{config.CACHE_DIR}/news/alpaca_news.parquet"
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        news.to_parquet(path)
        print(f"news: {len(news)} headlines → {path}")


if __name__ == "__main__":
    main()
