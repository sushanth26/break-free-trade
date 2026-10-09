"""Print labelled zones at a time, for checking against TradingView.

  python scripts/run_zones.py DELL --as-of "2026-10-09 11:00" --timeframes 5m 1h --period 10 --width 2
"""
import argparse

import _setup  # noqa: F401

import pandas as pd

import config
from config import ZoneConfig
from data.base import closed_bars, regular_hours
from data.csv_provider import CsvProvider
from engine.profile import build_profile
from engine.zones import label_zones, multi_timeframe_zones


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--timeframes", nargs="+", default=["5m"])
    ap.add_argument("--period", type=int, default=config.ZONE_DEFAULT.pivot_period)
    ap.add_argument("--width", type=float, default=config.ZONE_DEFAULT.channel_width_pct)
    ap.add_argument("--min-strength", type=int, default=config.ZONE_DEFAULT.min_strength)
    ap.add_argument("--provider", default="alpaca")
    args = ap.parse_args()

    src = CsvProvider(config.CACHE_DIR, cache_provider=args.provider)
    bars5 = regular_hours(src.get_bars(args.symbol, "5m"))
    daily = src.get_bars(args.symbol, "D")
    now = pd.Timestamp(args.as_of, tz=config.TZ) if args.as_of else bars5.index[-1] + pd.Timedelta("5min")
    cfg = ZoneConfig(pivot_period=args.period, channel_width_pct=args.width, min_strength=args.min_strength)
    zones = multi_timeframe_zones(bars5, tuple(args.timeframes), now, cfg, bars_daily=daily)
    price = float(closed_bars(bars5, "5m", now)["close"].iloc[-1])
    atr = build_profile(args.symbol, bars5, daily, now).atr_5m

    print(f"{args.symbol} @ {now:%Y-%m-%d %H:%M} · price {price:.2f} · 5m ATR {atr:.2f}")
    print(f"{'zone':<4} {'bottom':>9} {'top':>9} {'width ATR':>9} {'str':>4}  tf")
    for name, z in label_zones(zones, price):
        print(f"{name:<4} {z.bottom:>9.2f} {z.top:>9.2f} {z.width / atr:>9.2f} {z.strength_raw:>4}  "
              f"{'+'.join(z.timeframes)}")


if __name__ == "__main__":
    main()
