"""Day 1 gate: Alpaca vs Webull 5m bars on the days both cover.

Exits non-zero if any symbol fails; the backtest is blocked until it passes.

  python scripts/check_alignment.py --symbols SPY QQQ DELL SOXL NVDA
"""
import argparse
import sys

import _setup  # noqa: F401

import pandas as pd

import config
from data.alignment import compare_bars, mismatches
from data.alpaca_provider import AlpacaProvider
from data.webull_provider import WebullProvider


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=list(config.BUILD_STOCKS))
    ap.add_argument("--session", default="regular", choices=["regular", "extended"])
    ap.add_argument("--stamps-bar-end", action="store_true")
    ap.add_argument("--show", type=int, default=5, help="worst mismatched bars to list per symbol")
    args = ap.parse_args()

    alpaca, webull = AlpacaProvider(), WebullProvider(stamps_bar_end=args.stamps_bar_end)
    today = pd.Timestamp.now(tz=config.TZ).normalize()   # completed days only: today may still be forming
    start = today - pd.Timedelta(days=30)
    rows, worst = [], {}
    for sym in args.symbols:
        a, b = alpaca.get_bars(sym, "5m", start), webull.get_bars(sym, "5m")
        rows.append(compare_bars(a, b, sym, session=args.session, before=today))
        worst[sym] = mismatches(a, b, session=args.session, before=today)

    print(f"{'symbol':<6} {'pass':<4} {'matched':>7} {'onlyA':>5} {'onlyW':>5} {'shift':>5} "
          f"{'p95 ATR':>7} {'max ATR':>7} {'>0.1ATR':>7} {'>0.5ATR':>7} {'vol ok':>6} {'medVol%':>7}")
    for r in rows:
        print(f"{r.symbol:<6} {'yes' if r.passed else 'NO':<4} {r.matched:>7} {r.only_a:>5} {r.only_b:>5} "
              f"{r.best_shift_bars:>5} {r.price_p95_atr:>7.3f} {r.price_max_atr:>7.3f} {r.price_fail:>7} {r.price_outliers:>7} "
              f"{r.volume_within:>6.0%} {r.median_volume_diff_pct:>7.1f}")
    print(f"\npass: p95 <= {config.ALIGN_PRICE_P95_ATR} ATR, >{config.ALIGN_PRICE_MAX_ATR} ATR on <= "
          f"{config.ALIGN_OUTLIER_MAX_SHARE:.1%} of bars, vol ok >= {config.ALIGN_VOLUME_MIN_SHARE:.0%} "
          f"(bars {', '.join(config.ALIGN_SKIP_SLOTS)} skipped)")
    for sym, bad in worst.items():
        if args.show and len(bad):
            print(f"\n{sym}: {len(bad)} bars outside tolerance (A = Alpaca, W = Webull), worst {args.show}")
            cols = ["close_a", "close_b", "close_atr", "high_atr", "low_atr", "vol_a", "vol_b", "vol_pct"]
            print(bad[cols].head(args.show).rename(columns=lambda c: c.replace("_a", " A").replace("_b", " W"))
                  .to_string(float_format=lambda x: f"{x:.3f}"))
    if any(r.best_shift_bars for r in rows):
        print("\nTimestamp convention differs (shift != 0): rerun with --stamps-bar-end or fix the provider.")
    sys.exit(0 if all(r.passed for r in rows) else 1)


if __name__ == "__main__":
    main()
