"""Day 3 — Backtest 1 (zone quality): 144 configs, leaderboard, learned weights.

  python scripts/run_zone_backtest.py --jobs 8            # all configs, build stocks
  python scripts/run_zone_backtest.py --quick              # 1 combo x 18 settings, for a smoke run
  python scripts/run_zone_backtest.py --reuse              # re-learn weights + Day 3 gate from saved touches
  python scripts/run_zone_backtest.py --reuse --config "15m+1h|p5|w3|s2"   # gate + weights on a chosen config

Writes reports/zone_touches.parquet, reports/zone_leaderboard.csv,
models/zone_weights.json (learned on TRAIN touches of the best config).
"""
import argparse
from pathlib import Path

import _setup  # noqa: F401

import pandas as pd

import config
from backtest.zone_backtest import (SymbolData, config_grid, day3_gate, learn_weights, run_grid,
                                    save_weights, split_touches)
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
    ap.add_argument("--reuse", action="store_true",
                    help="skip the grid: reuse zone_touches.parquet + zone_leaderboard.csv from --out")
    ap.add_argument("--config", default=None,
                    help="run the gate + learn weights on this config id instead of the leaderboard's top pick "
                         "(e.g. '15m+1h|p5|w3|s2'); must be present in the saved touches")
    args = ap.parse_args()

    out = Path(args.out)
    if args.reuse:
        touches = pd.read_parquet(out / "zone_touches.parquet")
        board = pd.read_csv(out / "zone_leaderboard.csv")
        print(f"reusing {len(touches)} touches, {len(board)} configs from {out}/")
    else:
        datas = load(args.symbols)
        grid = config_grid()
        if args.quick:
            grid = [g for g in grid if g[0] == ("5m",)]
        print(f"{len(grid)} configs x {len(datas)} stocks")
        touches, board = run_grid(datas, grid, n_jobs=args.jobs)
        out.mkdir(exist_ok=True)
        touches.to_parquet(out / "zone_touches.parquet")
        board.to_csv(out / "zone_leaderboard.csv", index=False)

    print("\nTop 10 configs (train touches)")
    print(board.head(10).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    by_tf = board.assign(tf=board["config"].str.split("|").str[0]).groupby("tf").first()
    print("\nBest per timeframe combo")
    print(by_tf[["config", "touches", "hold_rate", "reaction_atr"]].to_string(float_format=lambda x: f"{x:.2f}"))

    if args.config:
        if args.config not in set(board["config"]):
            raise SystemExit(f"--config {args.config!r} not found in {out}/zone_leaderboard.csv")
        best = args.config
    else:
        best = board.iloc[0]["config"]
    train, _ = split_touches(touches[touches["config"] == best])   # out-of-sample stays untouched until Day 6
    gate = day3_gate(train)
    print(f"\nDay 3 gate — {best}: weights fit on {gate['n_fit']} train touches before "
          f"{config.ZONE_GATE_VALID_START}, bands on {gate['n_valid']} later train touches")
    print(gate["bands"].to_string(float_format=lambda x: f"{x:.2f}"))
    verdict = "PASS" if gate["passed"] else ("FAIL" if gate["enough"] else
                                              f"INCONCLUSIVE (a band has < {config.ZONE_GATE_MIN_TOUCHES} touches)")
    print(f"gate (80+ hold rate >= <50 hold rate + {config.ZONE_GATE_MIN_EDGE * 100:.0f} pts; "
          f"edge {gate['edge'] * 100:+.1f} pts): {verdict}")

    weights = learn_weights(train)                                   # final weights: all train touches
    path = save_weights({**weights, "config": best})
    print(f"\nWeights learned on {weights['n_train']} train touches of {best} → {path}")
    print(f"balance: w_s={weights['w_s']:.2f} w_b={weights['w_b']:.2f}")

if __name__ == "__main__":
    main()
