"""Backtest for engine/simple_bounce.py -- a separate, deliberately plain
strategy, run and reported on its own. Does not touch the main engine's
trade_backtest.py / tuning.py / report.py.

Reuses, unchanged, from the main pipeline:
  - zone construction + percentile scoring (backtest.zone_backtest, engine.scoring)
  - strength / break-risk factor functions (engine.strength, engine.break_risk)
  - honest fills (backtest.fills.FillModel)
  - the Day 3 gate (backtest.zone_backtest.day3_gate)

New here: the simple touch/entry/stop/target state machine's own trade loop,
since its rules are not the main engine's bounce/trade rules. The per-bar loop
reads feature rows as plain dicts (engine.features.feature_rows), the same
choice trade_backtest.py makes, rather than pandas .loc per bar.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import config
from backtest.fills import FillModel
from backtest.zone_backtest import (SymbolData, build_timeline, day3_gate, learn_weights, run_config,
                                    save_weights, split_touches)
from data.base import regular_hours, to_ts
from engine.break_risk import break_factors, break_risk_score
from engine.profile import round_step
from engine.scoring import raw_to_score
from engine.simple_bounce import ENTRY, TOUCH, SimpleBounceTracker, plan_simple_trade
from engine.strength import strength_factors, strength_score

TRADE_COLUMNS = ["symbol", "direction", "entry_time", "exit_time", "entry", "stop", "target", "shares",
                 "r_to_target", "win", "r", "pnl", "exit_reason", "score", "touched_only",
                 "zone_bottom", "zone_top"]
SKIP_COLUMNS = ["symbol", "time", "direction", "reason"]


# ------------------------------------------------------------------ Day 3-style zone quality + weights

def learn_simple_weights(datas: list[SymbolData]) -> tuple[pd.DataFrame, dict, dict]:
    """Touches (train only), learned percentile weights, and the Day 3 gate result."""
    touches = run_config(datas, (config.SIMPLE_ZONE_TIMEFRAME,), config.SIMPLE_ZONE_CONFIG)
    train, _ = split_touches(touches)                 # out-of-sample stays untouched
    gate = day3_gate(train)
    weights = learn_weights(train)
    cfg_id = (f"{config.SIMPLE_ZONE_TIMEFRAME}|p{config.SIMPLE_ZONE_CONFIG.pivot_period}|"
             f"w{config.SIMPLE_ZONE_CONFIG.channel_width_pct:g}|s{config.SIMPLE_ZONE_CONFIG.min_strength}")
    save_weights({**weights, "config": cfg_id}, path=config.SIMPLE_ZONE_WEIGHTS_PATH)
    return train, weights, gate


# ------------------------------------------------------------------ trade simulation

@dataclass
class _Position:
    symbol: str
    direction: str
    entry: float
    stop: float
    target: float
    shares: int
    entry_time: pd.Timestamp
    score: float
    commission_in: float
    zone_bottom: float
    zone_top: float


def _zone_score(zone, side, hist, row, rvol, weights) -> float:
    sf = strength_factors(zone, hist, row["atr"], round_step(row["close"]),
                          (row["prev_high"], row["prev_low"], row["prev_close"]))
    bf = break_factors(zone, side, hist, row["atr"], rvol, None, False)
    s = strength_score(sf, weights["strength"])
    b = break_risk_score(bf, weights["break"])
    raw = weights["w_s"] * s - weights["w_b"] * b
    return float(raw_to_score(raw, weights))


def simulate(datas: dict[str, SymbolData], weights: dict, start, end,
            fills: FillModel = FillModel()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bar-by-bar, all symbols in one time-ordered stream (one shared daily-loss limit),
    train period only. Returns (trades, skipped)."""
    lo, hi = to_ts(start), to_ts(end) + pd.Timedelta(days=1)
    e_start, e_end = config.SIMPLE_ENTRY_WINDOW

    timelines, bars_by_sym, rows_by_sym, rvol_by_sym = {}, {}, {}, {}
    for s, d in datas.items():
        timelines[s] = build_timeline(d, (config.SIMPLE_ZONE_TIMEFRAME,), config.SIMPLE_ZONE_CONFIG)
        reg = regular_hours(d.bars)
        reg = reg[(reg.index >= lo) & (reg.index < hi)]
        bars_by_sym[s] = reg
        all_rows = {r.name: r for r in d.rows}
        rows_by_sym[s] = [all_rows[t] for t in reg.index]
        rvol_by_sym[s] = d.feats["rvol"].reindex(reg.index)

    pos_by_time = {s: {t: i for i, t in enumerate(bars_by_sym[s].index)} for s in datas}
    stream = sorted((t, s) for s in datas for t in bars_by_sym[s].index)
    trackers: dict[str, dict] = {s: {} for s in datas}
    positions: dict[str, _Position | None] = {s: None for s in datas}
    day_key, day_pnl = None, 0.0
    trades, skipped = [], []

    for t, s in stream:
        i = pos_by_time[s][t]
        row = rows_by_sym[s][i]
        atr = row["atr"]
        now = t + pd.Timedelta("5min")
        hhmm = now.strftime("%H:%M")
        day = t.normalize()
        if day != day_key:
            day_key, day_pnl = day, 0.0
            for sym in trackers:
                trackers[sym] = {}        # don't carry an unresolved overnight setup into a new day
        if not (atr == atr) or atr <= 0:
            continue
        bar = {k: row[k] for k in ("open", "high", "low", "close", "volume")}

        zones = timelines[s](now)
        live = {}
        for z in zones:
            for direction in ("long", "short"):
                key = (z.bottom, z.top, direction)
                live[key] = trackers[s].get(key) or SimpleBounceTracker(z, direction)
        for key, tr in trackers[s].items():
            if key not in live and tr.stage == TOUCH:
                live[key] = tr
        trackers[s] = live
        updates = [tr.step(bar, atr) for tr in live.values()]

        pos = positions[s]
        if pos is not None:
            exit_px = exit_reason = None
            stop_hit = fills.stop_fill(pos.direction, pos.stop, bar)
            tgt_hit = fills.target_fill(pos.direction, pos.target, bar)
            if stop_hit is not None:                       # stop checked first (order of moves unknown)
                exit_px, exit_reason = stop_hit, "stop hit"
            elif tgt_hit is not None:
                exit_px, exit_reason = tgt_hit, "target hit"
            elif hhmm >= config.EOD_EXIT:
                exit_px = fills.market_fill(pos.direction, bar["close"], selling=True)
                exit_reason = "end of day"
            if exit_px is not None:
                long = pos.direction == "long"
                pnl = (exit_px - pos.entry if long else pos.entry - exit_px) * pos.shares
                pnl -= pos.commission_in + fills.commission(pos.shares)
                r = pnl / (abs(pos.entry - pos.stop) * pos.shares)
                day_pnl += pnl
                r_to_target = ((pos.target - pos.entry) / (pos.entry - pos.stop) if long
                              else (pos.entry - pos.target) / (pos.stop - pos.entry))
                trades.append({"symbol": s, "direction": pos.direction, "entry_time": pos.entry_time,
                              "exit_time": now, "entry": pos.entry, "stop": pos.stop, "target": pos.target,
                              "shares": pos.shares, "r_to_target": r_to_target,
                              "win": exit_reason == "target hit", "r": r, "pnl": pnl, "exit_reason": exit_reason,
                              "score": pos.score, "touched_only": False,
                              "zone_bottom": pos.zone_bottom, "zone_top": pos.zone_top})
                positions[s] = None
                pos = None

        if pos is None:
            for u in updates:
                if u.stage != ENTRY or not u.changed:
                    continue
                if not (e_start <= hhmm <= e_end):
                    skipped.append({"symbol": s, "time": now, "direction": u.direction, "reason": "outside entry window"})
                    continue
                if day_pnl <= -config.MAX_DAILY_LOSS:
                    skipped.append({"symbol": s, "time": now, "direction": u.direction, "reason": "daily loss limit reached"})
                    continue
                plan, why = plan_simple_trade(u, zones, atr)
                if plan is None:
                    skipped.append({"symbol": s, "time": now, "direction": u.direction, "reason": why})
                    continue
                risk = abs(plan["entry"] - plan["stop"])
                shares = int(config.RISK_PER_TRADE // risk)
                if shares < 1:
                    skipped.append({"symbol": s, "time": now, "direction": u.direction, "reason": "position size < 1 share"})
                    continue
                # "enter at that close" is a direct fill, not a resting limit order: no touch/through
                # ambiguity, so the adverse-selection rerun cannot differ from the base run on entries.
                fill_px = fills.market_fill(u.direction, plan["entry"], selling=False)
                hist = bars_by_sym[s].iloc[: i + 1]
                side = "support" if u.direction == "long" else "resistance"
                score = _zone_score(u.zone, side, hist, row, rvol_by_sym[s].iloc[: i + 1], weights)
                positions[s] = _Position(s, u.direction, fill_px, plan["stop"], plan["target"], shares,
                                        now, score, fills.commission(shares), u.zone.bottom, u.zone.top)
                break   # one new position per symbol per bar

    for s, pos in positions.items():
        if pos is not None:
            last_t = bars_by_sym[s].index[-1]
            px = fills.market_fill(pos.direction, rows_by_sym[s][-1]["close"], selling=True)
            long = pos.direction == "long"
            pnl = (px - pos.entry if long else pos.entry - px) * pos.shares - pos.commission_in - fills.commission(pos.shares)
            r = pnl / (abs(pos.entry - pos.stop) * pos.shares)
            trades.append({"symbol": s, "direction": pos.direction, "entry_time": pos.entry_time,
                          "exit_time": last_t, "entry": pos.entry, "stop": pos.stop, "target": pos.target,
                          "shares": pos.shares, "r_to_target": float("nan"), "win": False, "r": r, "pnl": pnl,
                          "exit_reason": "end of data", "score": pos.score, "touched_only": False,
                          "zone_bottom": pos.zone_bottom, "zone_top": pos.zone_top})

    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=TRADE_COLUMNS)
    skipped_df = pd.DataFrame(skipped) if skipped else pd.DataFrame(columns=SKIP_COLUMNS)
    return trades_df, skipped_df


# ------------------------------------------------------------------ reporting

def summarize(trades: pd.DataFrame) -> dict:
    if not len(trades):
        return {"trades": 0}
    wins = trades["win"]
    gains = trades.loc[wins, "r"].sum()
    losses = -trades.loc[~wins, "r"].sum()
    return {
        "trades": len(trades),
        "win_rate": float(wins.mean()),
        "profit_factor": float(gains / losses) if losses > 0 else float("inf"),
        "expectancy_r": float(trades["r"].mean()),
        "avg_win_r": float(trades.loc[wins, "r"].mean()) if wins.any() else float("nan"),
        "avg_loss_r": float(-trades.loc[~wins, "r"].mean()) if (~wins).any() else float("nan"),
    }


def by_band(trades: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    t["band"] = pd.cut(t["score"], [-1, 49.999, 79.999, 101], labels=["<50", "50-79", "80+"])
    return pd.DataFrame([{"band": b, **summarize(g)} for b, g in t.groupby("band", observed=False)])


def by_direction(trades: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{"direction": d, **summarize(g)} for d, g in trades.groupby("direction")])


def by_symbol(trades: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{"symbol": s, **summarize(g)} for s, g in trades.groupby("symbol")])


def save_chart_review(trades: pd.DataFrame, path: str, n: int = 20, seed: int = 0) -> pd.DataFrame:
    if len(trades) <= n:
        sample = trades
    else:
        rng = np.random.default_rng(seed)
        idx = rng.choice(trades.index, size=n, replace=False)
        sample = trades.loc[sorted(idx)]
    cols = ["symbol", "direction", "entry_time", "zone_bottom", "zone_top", "entry", "stop", "target",
           "exit_time", "exit_reason", "r", "score"]
    out = sample[cols].sort_values("entry_time")
    out.to_csv(path, index=False)
    return out
