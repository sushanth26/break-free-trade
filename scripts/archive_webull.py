"""After the close: save today's Webull bars to the CSV archive (one file per day).

  python scripts/archive_webull.py --symbols DELL NVDA --timeframes 5m 1m
"""
import argparse

import _setup  # noqa: F401

import config
from data.csv_provider import write_day_csv
from data.webull_provider import WebullProvider


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=list(dict.fromkeys(config.BUILD_STOCKS + config.CONTEXT_SYMBOLS)))
    ap.add_argument("--timeframes", nargs="+", default=["5m", "1m"])
    ap.add_argument("--stamps-bar-end", action="store_true",
                    help="set if the alignment check shows Webull stamps bars with their end time")
    args = ap.parse_args()

    provider = WebullProvider(stamps_bar_end=args.stamps_bar_end)
    for sym in args.symbols:
        for tf in args.timeframes:
            bars = provider.get_bars(sym, tf)
            files = write_day_csv(bars, sym, tf, config.ARCHIVE_DIR)
            print(f"{sym:<6} {tf:<3} {len(bars):>5} bars → {len(files)} day files")


if __name__ == "__main__":
    main()
