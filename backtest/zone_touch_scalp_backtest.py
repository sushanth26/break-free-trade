"""Zone-touch scalp -- mirrors the Day 3 hold/break labels exactly, as an actual
tradeable setup with real fills, costs and slippage. A third, independent
strategy: does not touch engine/bounce.py, engine/simple_bounce.py, or either
of their backtests.

Rule: the FIRST 5m touch of each zone, each day (as backtest.labels.find_touches
defines a touch), fires a limit order at the zone edge, filled only if price
trades through by a tick (backtest.fills.FillModel(adverse_selection=True)) --
required for the fill check to mean anything at all here, since the touch
condition (low <= zone top) and a bare "touched" fill check (reach <= limit)
are the same condition for a limit AT the zone edge; every touch would
otherwise fill trivially. Target/stop are exactly the distances Day 3 used to
label a touch held (HOLD_MOVE_ATR) or broken (BREAK_ATR). Only zones already
scored (via the learned simple-bounce weights) at >= min_score are traded.
"""
from __future__ import annotations

import pandas as pd

import config
from backtest.fills import FillModel
from engine.zone_assistant import zone_score_from_bars as zone_score_at
from backtest.zone_backtest import SymbolData, build_timeline
from data.base import regular_hours, to_ts

TRADE_COLUMNS = ["symbol", "direction", "entry_time", "exit_time", "entry", "stop", "target", "shares",
                 "win", "r", "pnl", "exit_reason", "score", "touched_only", "zone_bottom", "zone_top"]
SKIP_COLUMNS = ["symbol", "time", "direction", "reason"]


def simulate(datas: dict[str, SymbolData], weights: dict, start, end,
            fills: FillModel = FillModel(adverse_selection=True),
            min_score: float = 80.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bar-by-bar, all symbols in one time-ordered stream (one shared daily-loss
    limit, one position per symbol). Returns (trades, skipped)."""
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
    positions: dict[str, dict | None] = {s: None for s in datas}
    touched_today: dict[str, set] = {s: set() for s in datas}   # zones that already had their one touch today
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
            for sym in touched_today:
                touched_today[sym] = set()
        if not (atr == atr) or atr <= 0:
            continue
        bar = {k: row[k] for k in ("open", "high", "low", "close", "volume")}
        prev_row = rows_by_sym[s][i - 1] if i > 0 else None
        same_day_prev = prev_row is not None and prev_row.name.normalize() == day

        pos = positions[s]
        if pos is not None:
            exit_px = exit_reason = None
            stop_hit = fills.stop_fill(pos["direction"], pos["stop"], bar)
            tgt_hit = fills.target_fill(pos["direction"], pos["target"], bar)
            if stop_hit is not None:                       # stop checked first (order of moves unknown)
                exit_px, exit_reason = stop_hit, "stop hit"
            elif tgt_hit is not None:
                exit_px, exit_reason = tgt_hit, "target hit"
            elif hhmm >= config.EOD_EXIT:
                exit_px = fills.market_fill(pos["direction"], bar["close"], selling=True)
                exit_reason = "end of day"
            if exit_px is not None:
                long = pos["direction"] == "long"
                pnl = (exit_px - pos["entry"] if long else pos["entry"] - exit_px) * pos["shares"]
                pnl -= pos["commission_in"] + fills.commission(pos["shares"])
                r = pnl / (abs(pos["entry"] - pos["stop"]) * pos["shares"])
                day_pnl += pnl
                trades.append({"symbol": s, "direction": pos["direction"], "entry_time": pos["entry_time"],
                              "exit_time": now, "entry": pos["entry"], "stop": pos["stop"],
                              "target": pos["target"], "shares": pos["shares"],
                              "win": exit_reason == "target hit", "r": r, "pnl": pnl, "exit_reason": exit_reason,
                              "score": pos["score"], "touched_only": pos["touched_only"],
                              "zone_bottom": pos["zone_bottom"], "zone_top": pos["zone_top"]})
                positions[s] = None
                pos = None

        if pos is None and same_day_prev:
            candidates = [(z, d) for z in timelines[s](now) for d in ("long", "short")]
            for z, direction in candidates:
                key = (z.bottom, z.top, direction)
                if key in touched_today[s]:
                    continue
                if direction == "long":
                    touch = prev_row["close"] > z.top and bar["low"] <= z.top
                else:
                    touch = prev_row["close"] < z.bottom and bar["high"] >= z.bottom
                if not touch:
                    continue
                touched_today[s].add(key)      # only the FIRST touch of the day is eligible, fill or not
                if not (e_start <= hhmm <= e_end):
                    skipped.append({"symbol": s, "time": now, "direction": direction, "reason": "outside entry window"})
                    continue
                if day_pnl <= -config.MAX_DAILY_LOSS:
                    skipped.append({"symbol": s, "time": now, "direction": direction, "reason": "daily loss limit reached"})
                    continue
                hist = bars_by_sym[s].iloc[: i + 1]
                side = "support" if direction == "long" else "resistance"
                score = zone_score_at(z, side, hist, row, rvol_by_sym[s].iloc[: i + 1], weights)
                if score < min_score:
                    skipped.append({"symbol": s, "time": now, "direction": direction,
                                   "reason": f"zone score {score:.0f} < {min_score:g}"})
                    continue
                limit = z.top if direction == "long" else z.bottom
                fill = fills.entry_fill(direction, limit, bar)
                if fill is None:
                    skipped.append({"symbol": s, "time": now, "direction": direction, "reason": "touched but not through"})
                    continue
                fill_px, touched_only = fill
                stop = (z.bottom - config.BREAK_ATR * atr if direction == "long"
                       else z.top + config.BREAK_ATR * atr)
                target = (z.top + config.HOLD_MOVE_ATR * atr if direction == "long"
                         else z.bottom - config.HOLD_MOVE_ATR * atr)
                risk = abs(fill_px - stop)
                shares = int(config.RISK_PER_TRADE // risk)
                if shares < 1:
                    skipped.append({"symbol": s, "time": now, "direction": direction, "reason": "position size < 1 share"})
                    continue
                positions[s] = {"direction": direction, "entry": fill_px, "stop": stop, "target": target,
                               "shares": shares, "entry_time": now, "score": score,
                               "commission_in": fills.commission(shares), "touched_only": touched_only,
                               "zone_bottom": z.bottom, "zone_top": z.top}
                break   # one new position per symbol per bar

    for s, pos in positions.items():
        if pos is not None:
            last_t = bars_by_sym[s].index[-1]
            px = fills.market_fill(pos["direction"], rows_by_sym[s][-1]["close"], selling=True)
            long = pos["direction"] == "long"
            pnl = ((px - pos["entry"] if long else pos["entry"] - px) * pos["shares"]
                  - pos["commission_in"] - fills.commission(pos["shares"]))
            r = pnl / (abs(pos["entry"] - pos["stop"]) * pos["shares"])
            trades.append({"symbol": s, "direction": pos["direction"], "entry_time": pos["entry_time"],
                          "exit_time": last_t, "entry": pos["entry"], "stop": pos["stop"],
                          "target": pos["target"], "shares": pos["shares"], "win": False, "r": r, "pnl": pnl,
                          "exit_reason": "end of data", "score": pos["score"], "touched_only": pos["touched_only"],
                          "zone_bottom": pos["zone_bottom"], "zone_top": pos["zone_top"]})

    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=TRADE_COLUMNS)
    skipped_df = pd.DataFrame(skipped) if skipped else pd.DataFrame(columns=SKIP_COLUMNS)
    return trades_df, skipped_df
