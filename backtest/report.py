"""Day 6 — out-of-sample + robustness report.

Runs the chosen settings ONCE on untouched data: later months of the build
stocks, and all 12 months of the unseen validation stocks. Adds the
adverse-selection rerun, neighbouring settings, walk-forward stability and
breakdowns, then writes a short Markdown report and the 50-trade sample for
the mandatory TradingView chart review.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import config
from backtest.fills import FillModel
from backtest.metrics import add_time_buckets, breakdown, passes, summarize
from backtest.split import walk_forward_windows
from backtest.trade_backtest import BacktestInput, run_backtest
from backtest.tuning import choose, evaluate, neighbours, settings_id
from engine.settings import EngineSettings

KEY_METRICS = ["trades", "win_rate", "win_rate_low", "avg_win_r", "avg_loss_r", "expectancy_r",
               "expectancy_worst_r", "profit_factor", "max_drawdown_r", "trades_per_day"]


def _fmt(d: dict) -> dict:
    return {k: (f"{v:.2f}" if isinstance(v, float) else v) for k, v in d.items() if k in KEY_METRICS}


def _table(rows: dict[str, dict]) -> str:
    df = pd.DataFrame({k: _fmt(v) for k, v in rows.items()}).T
    return df.to_markdown() if len(df) else "_no trades_"


def walk_forward(inp: BacktestInput, candidates: list[EngineSettings], symbols, start, end,
                 n_jobs: int = 1, min_trades: int = 20) -> pd.DataFrame:
    """Each window: pick the best candidate on its 3-month train, test it on the next month."""
    rows = []
    for tr0, tr1, te0, te1 in walk_forward_windows(start, end):
        res = choose(evaluate(inp, candidates, tr0, tr1, symbols, n_jobs), min_trades)
        best_id = res.iloc[0]["settings_id"]
        best = next(s for s in candidates if settings_id(s) == best_id)
        trades, _ = run_backtest(inp, best, FillModel(), te0, te1, symbols)
        rows.append({"test_month": te0.strftime("%Y-%m"), "settings_id": best_id, **summarize(trades)})
    return pd.DataFrame(rows)


def robustness_report(build: BacktestInput, valid: BacktestInput | None, settings: EngineSettings,
                      candidates: list[EngineSettings] | None = None, out_dir: str = "reports",
                      n_jobs: int = 1, seed: int = 0) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fills = FillModel()
    build_syms = [s for s in config.BUILD_STOCKS if s in build.datas]

    train, _ = run_backtest(build, settings, fills, config.TRAIN_START, config.TRAIN_END, build_syms)
    oos_time, _ = run_backtest(build, settings, fills, config.OOS_START, config.OOS_END, build_syms)
    parts = [oos_time.assign(sample="oos_time")]
    if valid is not None:
        vsyms = [s for s in config.VALIDATION_STOCKS if s in valid.datas]
        oos_stocks, _ = run_backtest(valid, settings, fills, symbols=vsyms)
        parts.append(oos_stocks.assign(sample="oos_stocks"))
    oos = pd.concat(parts, ignore_index=True)

    adv_parts = [run_backtest(build, settings, FillModel(adverse_selection=True), config.OOS_START,
                              config.OOS_END, build_syms)[0]]
    if valid is not None:
        adv_parts.append(run_backtest(valid, settings, FillModel(adverse_selection=True), symbols=vsyms)[0])
    adverse = pd.concat(adv_parts, ignore_index=True)

    summaries = {"train": summarize(train), "oos_time": summarize(oos_time),
                 "oos_all": summarize(oos), "oos_adverse": summarize(adverse)}
    if valid is not None:
        summaries["oos_stocks"] = summarize(oos_stocks)

    nb = evaluate(build, neighbours(settings), config.OOS_START, config.OOS_END, build_syms, n_jobs)
    nb_pass = [all(passes(r.to_dict(), min_trades=1).values()) for _, r in nb.iterrows()] if len(nb) else []

    wf = walk_forward(build, candidates or [settings], build_syms, config.TRAIN_START, config.OOS_END, n_jobs)

    checks = passes(summaries["oos_all"])
    checks["adverse_selection"] = all(passes(summaries["oos_adverse"]).values())
    checks["neighbours"] = bool(nb_pass) and all(nb_pass)
    checks["chart_review"] = False          # set by the trader after reviewing the sample

    oos_b = add_time_buckets(oos)
    closed = oos[oos["state"] == "closed"]
    sample = closed.sample(min(50, len(closed)), random_state=seed) if len(closed) else closed
    sample.to_csv(out / "chart_review_sample.csv", index=False)
    oos.to_csv(out / "oos_trades.csv", index=False)

    lines = [
        f"# Robustness report — {settings_id(settings)}",
        "",
        "## Pass checks (out-of-sample)",
        "",
        "| check | result |", "|---|---|",
        *[f"| {k} | {'✅' if v else '❌'} |" for k, v in checks.items()],
        "",
        "Chart review: check the 50 trades in `chart_review_sample.csv` on TradingView "
        "(zones, entry, stop, exit must match). Until then the result does not count.",
        "",
        "## Summary", "", _table(summaries), "",
        "## Walk-forward (3-month train → 1-month test)", "",
        wf[["test_month", "settings_id"] + [c for c in KEY_METRICS if c in wf]].to_markdown(index=False, floatfmt=".2f")
        if len(wf) else "_none_", "",
        "## Neighbouring settings (out-of-sample time)", "",
        nb[["settings_id"] + [c for c in KEY_METRICS if c in nb]].to_markdown(index=False, floatfmt=".2f")
        if len(nb) else "_none_", "",
    ]
    for by in ("symbol", "regime", "time_bucket", "catalyst", "entry_mode", "premarket", "grade"):
        if by in oos_b and len(oos_b):
            b = breakdown(oos_b, by)
            if len(b):
                lines += [f"## By {by}", "", b[[c for c in KEY_METRICS if c in b]].to_markdown(floatfmt=".2f"), ""]
    (out / "robustness_report.md").write_text("\n".join(lines))
    return {"checks": checks, "summaries": summaries, "walk_forward": wf, "neighbours": nb}
