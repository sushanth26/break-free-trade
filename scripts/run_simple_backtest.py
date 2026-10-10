"""Simple-bounce backtest: zone weights + Day 3 gate + trade simulation, train only.

  python scripts/run_simple_backtest.py

No tuning: runs once on config.SIMPLE_* settings and reports the result.
"""
import argparse
from pathlib import Path

import _setup  # noqa: F401

import config
from backtest.fills import FillModel
from backtest.simple_bounce_backtest import (by_band, by_direction, by_symbol, learn_simple_weights,
                                             save_chart_review, simulate, summarize)
from backtest.zone_backtest import SymbolData
from data.csv_provider import CsvProvider


def load(symbols, provider="alpaca"):
    src = CsvProvider(config.CACHE_DIR, cache_provider=provider)
    out = []
    for s in symbols:
        bars, daily = src.get_bars(s, "5m"), src.get_bars(s, "D")
        if len(bars) == 0:
            print(f"skip {s}: no cached bars (run download_history.py)")
            continue
        out.append(SymbolData(s, bars, daily))
    return out


def show(title, d):
    print(f"\n{title}")
    for k, v in d.items():
        print(f"  {k:<16} {v:.3f}" if isinstance(v, float) else f"  {k:<16} {v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=list(config.SIMPLE_STOCKS))
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(exist_ok=True)

    datas_list = load(args.symbols)
    datas = {d.symbol: d for d in datas_list}
    z = config.SIMPLE_ZONE_CONFIG
    print(f"zone config: {config.SIMPLE_ZONE_TIMEFRAME} p{z.pivot_period} w{z.channel_width_pct:g}% "
          f"s{z.min_strength} max{z.max_zones} loopback{z.loopback}  ({len(datas)} symbols)")

    train_touches, weights, gate = learn_simple_weights(datas_list)
    print(f"\nDay 3 gate (simple-bounce zones) -- weights fit on {gate['n_fit']} train touches before "
          f"{config.ZONE_GATE_VALID_START}, bands on {gate['n_valid']} later train touches")
    print(gate["bands"].to_string(float_format=lambda x: f"{x:.2f}"))
    verdict = ("PASS" if gate["passed"] else
              "FAIL" if gate["enough"] else f"INCONCLUSIVE (a band has < {config.ZONE_GATE_MIN_TOUCHES} touches)")
    print(f"gate (80+ hold rate >= <50 hold rate + {config.ZONE_GATE_MIN_EDGE * 100:.0f} pts; "
          f"edge {gate['edge'] * 100:+.1f} pts): {verdict}")

    print(f"\nSimulating trades, train only ({config.TRAIN_START} .. {config.TRAIN_END})...")
    trades, skipped = simulate(datas, weights, config.TRAIN_START, config.TRAIN_END, FillModel())
    adverse, _ = simulate(datas, weights, config.TRAIN_START, config.TRAIN_END, FillModel(adverse_selection=True))

    show("All trades", summarize(trades))
    print("\nBy score band")
    print(by_band(trades).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\nBy direction")
    print(by_direction(trades).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\nBy symbol")
    print(by_symbol(trades).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\nSkip reasons")
    print(skipped["reason"].value_counts().to_string() if len(skipped) else "none")
    show("Adverse-selection rerun", summarize(adverse))

    trades.to_csv(out / "simple_trades.csv", index=False)
    skipped.to_csv(out / "simple_skipped.csv", index=False)
    review = save_chart_review(trades, str(out / "simple_chart_review.csv"))
    print(f"\n{len(trades)} trades -> {out}/simple_trades.csv")
    print(f"{len(review)} trades -> {out}/simple_chart_review.csv")


if __name__ == "__main__":
    main()
