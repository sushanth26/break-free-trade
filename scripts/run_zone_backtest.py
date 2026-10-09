"""Day 3 — Backtest 1 (zone quality): 144 configs, leaderboard, learned weights.

  python scripts/run_zone_backtest.py --jobs 8            # all configs, build stocks
  python scripts/run_zone_backtest.py --quick              # 1 combo x 18 settings, for a smoke run

Writes reports/zone_touches.parquet, reports/zone_leaderboard.csv,
models/zone_weights.json (learned on TRAIN touches of the best config).
"""
import argparse
from pathlib import Path

import _setup  # noqa: F401

import pandas as pd

import config
from backtest.zone_backtest import (SymbolData, apply_weights, config_grid, learn_weights, run_grid,
                                    save_weights, score_bands, split_touches)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=list(config.BUILD_STOCKS))
    ap.add_argument("--jobs", type=int, default=-1)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    datas = load(args.symbols)
    grid = config_grid()
    if args.quick:
        grid = [g for g in grid if g[0] == ("5m",)]
    print(f"{len(grid)} configs x {len(datas)} stocks")
    touches, board = run_grid(datas, grid, n_jobs=args.jobs)
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    touches.to_parquet(out / "zone_touches.parquet")
    board.to_csv(out / "zone_leaderboard.csv", index=False)

    print("\nTop 10 configs (train touches)")
    print(board.head(10).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    by_tf = board.assign(tf=board["config"].str.split("|").str[0]).groupby("tf").first()
    print("\nBest per timeframe combo")
    print(by_tf[["config", "touches", "hold_rate", "reaction_atr"]].to_string(float_format=lambda x: f"{x:.2f}"))

    best = board.iloc[0]["config"]
    train, oos = split_touches(touches[touches["config"] == best])
    weights = learn_weights(train)
    path = save_weights({**weights, "config": best})
    print(f"\nWeights learned on {weights['n_train']} train touches of {best} → {path}")
    print(f"balance: w_s={weights['w_s']:.2f} w_b={weights['w_b']:.2f}")
    for name, part in (("train", train), ("out-of-sample", oos)):
        if len(part):
            print(f"\nScore bands — {name}")
            print(score_bands(apply_weights(part, weights)).to_string(float_format=lambda x: f"{x:.2f}"))


if __name__ == "__main__":
    main()
