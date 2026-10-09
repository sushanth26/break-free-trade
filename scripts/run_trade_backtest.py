"""Days 5-6 — Backtest 2 (trades): tune on train, then the out-of-sample report.

  python scripts/run_trade_backtest.py tune --jobs 8          # Day 5: train only → models/engine_settings.json
  python scripts/run_trade_backtest.py report --jobs 8        # Day 6: OOS once + robustness report
  python scripts/run_trade_backtest.py run --start 2026-07-01 --end 2026-10-16   # one run with saved settings

Needs cached bars (download_history.py) for build, validation and context
symbols; uses reports/zone_leaderboard.csv from run_zone_backtest.py.
"""
import argparse
from pathlib import Path

import _setup  # noqa: F401

import pandas as pd

import config
from backtest.metrics import passes, summarize
from backtest.report import robustness_report
from backtest.trade_backtest import BacktestInput, run_backtest
from backtest.tuning import (LEVERS, choose, evaluate, lever_grid, load_settings, save_settings,
                             settings_id, zone_settings_from_id)
from backtest.zone_backtest import SymbolData
from data.csv_provider import CsvProvider
from engine.regime import market_regime
from engine.settings import EngineSettings


def load_datas(symbols, provider="alpaca"):
    src = CsvProvider(config.CACHE_DIR, cache_provider=provider)
    out = {}
    for s in symbols:
        b = src.get_bars(s, "5m")
        if len(b):
            out[s] = SymbolData(s, b, src.get_bars(s, "D"))
        else:
            print(f"skip {s}: no cached bars")
    return out


def load_extras():
    news = None
    for p in ("cache/news/judged_news.parquet", "cache/news/alpaca_news.parquet"):
        if Path(p).exists():
            news = pd.read_parquet(p)
            break
    econ = earn = None
    try:
        from data.calendar import load_earnings, load_economic
        econ, earn = load_economic(), load_earnings()
    except Exception as e:  # empty calendars are fine
        print(f"calendars not loaded: {e}")
    return news, econ, earn


def build_inputs(include_valid=True):
    ctx = load_datas(sorted(set(config.BUILD_STOCKS + config.CONTEXT_SYMBOLS)))
    market = market_regime({s: ctx[s].feats for s in config.REGIME_SYMBOLS if s in ctx})
    news, econ, earn = load_extras()
    build = BacktestInput({s: ctx[s] for s in config.BUILD_STOCKS if s in ctx}, market, news, econ, earn)
    valid = None
    if include_valid:
        vd = load_datas(config.VALIDATION_STOCKS)
        valid = BacktestInput(vd, market, news, econ, earn) if vd else None
    return build, valid


def candidates(top_zone_configs: int, quick: bool) -> list[EngineSettings]:
    board = pd.read_csv("reports/zone_leaderboard.csv")
    ids = board[board["eligible"]]["config"].head(top_zone_configs).tolist() or board["config"].head(top_zone_configs).tolist()
    levers = {k: v[:1] for k, v in LEVERS.items()} if quick else LEVERS
    out = []
    for cid in ids:
        tfs, z = zone_settings_from_id(cid)
        out += lever_grid(EngineSettings(zone=z, timeframes=tfs), levers)
    return out


def show(title, d):
    print(f"\n{title}")
    for k in ("trades", "win_rate", "win_rate_low", "avg_win_r", "avg_loss_r", "expectancy_r",
              "expectancy_worst_r", "profit_factor", "max_drawdown_r", "trades_per_day"):
        if k in d:
            print(f"  {k:<20} {d[k]:.3f}" if isinstance(d[k], float) else f"  {k:<20} {d[k]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["tune", "report", "run"])
    ap.add_argument("--jobs", type=int, default=-1)
    ap.add_argument("--top", type=int, default=10, help="zone configs from Backtest 1")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--start")
    ap.add_argument("--end")
    args = ap.parse_args()
    Path("reports").mkdir(exist_ok=True)

    if args.mode == "tune":
        build, _ = build_inputs(include_valid=False)
        cands = candidates(args.top, args.quick)
        print(f"tuning {len(cands)} settings on train {config.TRAIN_START}..{config.TRAIN_END}")
        res = choose(evaluate(build, cands, config.TRAIN_START, config.TRAIN_END, list(build.datas), args.jobs))
        res.to_csv("reports/tuning_train.csv", index=False)
        best_id = res.iloc[0]["settings_id"]
        best = next(s for s in cands if settings_id(s) == best_id)
        save_settings(best, extra={"chosen_on": "train"})
        print(res.head(10).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
        show(f"chosen: {best_id}", res.iloc[0].to_dict())
    elif args.mode == "report":
        build, valid = build_inputs()
        settings = load_settings()
        cands = None
        if Path("reports/tuning_train.csv").exists():
            top_ids = pd.read_csv("reports/tuning_train.csv")["settings_id"].head(20).tolist()
            pool = candidates(args.top, False)
            cands = [s for s in pool if settings_id(s) in top_ids] or None
        r = robustness_report(build, valid, settings, cands, n_jobs=args.jobs)
        show("out-of-sample", r["summaries"]["oos_all"])
        print("\nchecks:", r["checks"])
        print("report → reports/robustness_report.md · chart review sample → reports/chart_review_sample.csv")
    else:
        build, valid = build_inputs()
        inp = build
        trades, skipped = run_backtest(inp, load_settings(), start=args.start, end=args.end)
        trades.to_csv("reports/trades.csv", index=False)
        s = summarize(trades)
        show("summary", s)
        print("pass checks:", passes(s))
        if len(skipped):
            print("\nskipped signals:\n", skipped["reason"].value_counts().head(10).to_string())


if __name__ == "__main__":
    main()
