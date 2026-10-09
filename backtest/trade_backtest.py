"""Day 5 — Backtest 2: full trades, bar by bar, with the live engine modules.

All symbols are walked together in time order so daily limits apply across
the account. On each bar, an open position/pending order is updated first
(intrabar fills), then the engine runs at the bar close; a new order starts
working on the next bar. One position per symbol.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config
from backtest.fills import FillModel
from backtest.labels import ZoneTimeline
from backtest.zone_backtest import SymbolData, build_timeline
from data.base import to_ts
from engine.pipeline import BarContext, SymbolEngine
from engine.regime import RegimeLookup
from engine.settings import EngineSettings
from engine.trade import Position


@dataclass
class BacktestInput:
    datas: dict[str, SymbolData]
    market: pd.DataFrame                      # engine.regime.market_regime output
    news: pd.DataFrame | None = None          # data.news frame (+ optional 'bias' column from the judge)
    economic: pd.DataFrame | None = None      # data.calendar.load_economic
    earnings: pd.DataFrame | None = None      # data.calendar.load_earnings
    timelines: dict[tuple, ZoneTimeline] = field(default_factory=dict)

    def timeline(self, symbol: str, settings: EngineSettings) -> ZoneTimeline:
        key = (symbol, settings.timeframes, settings.zone)
        if key not in self.timelines:
            self.timelines[key] = build_timeline(self.datas[symbol], settings.timeframes, settings.zone)
        return self.timelines[key]


TRADE_COLUMNS = ["symbol", "direction", "signal_time", "fill_time", "exit_time", "state", "entry", "entry_fill",
                 "stop", "t1", "t2", "shares", "r_to_t1", "win", "r", "pnl", "exit_reason", "touched_only",
                 "grade", "aplus", "zone_score", "regime", "premarket", "zone_bottom", "zone_top", "timeframes"]
SKIP_COLUMNS = ["symbol", "time", "direction", "bottom", "top", "reason"]


class RiskManager:
    """Stop for the day after MAX_CONSECUTIVE_LOSSES losses in a row or MAX_DAILY_LOSS dollars."""

    def __init__(self):
        self.day = None
        self.streak = 0
        self.pnl = 0.0

    def _roll(self, t):
        d = t.normalize()
        if d != self.day:
            self.day, self.streak, self.pnl = d, 0, 0.0

    def allows(self, t) -> bool:
        self._roll(t)
        return self.streak < config.MAX_CONSECUTIVE_LOSSES and self.pnl > -config.MAX_DAILY_LOSS

    def record(self, t, pnl: float):
        self._roll(t)
        self.pnl += pnl
        self.streak = self.streak + 1 if pnl < 0 else 0


def _news_index(news: pd.DataFrame | None, symbol: str):
    if news is None or news.empty:
        return None
    rows = news[news["symbols"].apply(lambda s: symbol in s)]
    return rows.sort_values("published_at").reset_index(drop=True)


def _window_mask(index_close: pd.DatetimeIndex, economic: pd.DataFrame | None) -> np.ndarray:
    mask = np.zeros(len(index_close), dtype=bool)
    if economic is None or economic.empty:
        return mask
    before, after = (pd.Timedelta(minutes=m) for m in config.NEWS_WINDOW)
    for et in economic["time"]:
        mask |= (index_close >= et + before) & (index_close <= et + after)
    return mask


def run_backtest(inp: BacktestInput, settings: EngineSettings = EngineSettings(),
                 fills: FillModel = FillModel(), start=None, end=None,
                 symbols: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """→ (trades, skipped signals). Features use full history for warm-up; trading is limited to start..end."""
    symbols = symbols or list(inp.datas)
    lo = to_ts(start) if start is not None else None
    hi = to_ts(end) + pd.Timedelta(days=1) if end is not None else None

    engines, feats, rows, bars, news_ix, win_mask, earn_weeks, rvols = {}, {}, {}, {}, {}, {}, {}, {}
    regime_at = RegimeLookup(inp.market)
    for s in symbols:
        d = inp.datas[s]
        engines[s] = SymbolEngine(s, inp.timeline(s, settings), settings)
        feats[s], rows[s], bars[s], rvols[s] = d.feats, d.rows, d.bars, d.feats["rvol"]
        news_ix[s] = _news_index(inp.news, s)
        win_mask[s] = _window_mask(d.feats.index + pd.Timedelta("5min"), inp.economic)
        earn_weeks[s] = set()
        if inp.earnings is not None and not inp.earnings.empty:
            for dt in inp.earnings.loc[inp.earnings["symbol"] == s, "date"]:
                earn_weeks[s].add(tuple(pd.Timestamp(dt).isocalendar()[:2]))

    stream = sorted((t, s, i) for s in symbols for i, t in enumerate(feats[s].index)
                    if (lo is None or t >= lo) and (hi is None or t < hi))
    # warm-up: engines need the bar before the first traded bar
    for s in symbols:
        first = next((i for t, ss, i in stream if ss == s), None)
        if first:
            engines[s].prev_row = rows[s][first - 1]

    risk = RiskManager()
    positions: dict[str, Position | None] = {s: None for s in symbols}
    trades, skipped = [], []
    prev_regime: dict[str, str] = {}

    for t, s, i in stream:
        row = rows[s][i]
        now = t + pd.Timedelta("5min")
        regime, gap_dir, confirmed = regime_at(now)
        ctx = BarContext(regime=regime, gap_dir=gap_dir, regime_confirmed=confirmed,
                         prev_regime=prev_regime.get(s), in_news_window=bool(win_mask[s][i]),
                         earnings_week=tuple(now.isocalendar()[:2]) in earn_weeks[s])
        prev_regime[s] = regime
        nx = news_ix[s]
        if nx is not None:
            lo_t = now - pd.Timedelta(minutes=config.CATALYST_LOOKBACK_MIN)
            a, b = nx["published_at"].searchsorted([lo_t, now], side="left")
            recent = nx.iloc[a:b]
            ctx.catalyst = len(recent) > 0
            if "bias" in recent and len(recent):
                ctx.news_bias = str(recent["bias"].iloc[-1] or "")
            new_a = nx["published_at"].searchsorted(now - pd.Timedelta("5min"), side="left")
            ctx.headlines = nx.iloc[new_a:b] if b > new_a else None

        pos = positions[s]
        if pos is not None:
            bar = {k: row[k] for k in ("open", "high", "low", "close", "volume")}
            pos.on_bar(t, bar, row, news_against=ctx.news_against(pos.plan.direction))
            if pos.state in ("closed", "cancelled"):
                trades.append(pos.record())
                if pos.state == "closed":
                    risk.record(t, pos.pnl - pos.commission)
                positions[s] = None

        res = engines[s].on_bar(t, row, bars[s].iloc[: i + 1], ctx, rvols[s])
        skipped += res.skipped
        if positions[s] is None and res.plans:
            if risk.allows(now):
                positions[s] = Position(res.plans[0], fills)
            else:
                skipped.append({"symbol": s, "time": now, "direction": res.plans[0].direction,
                                "bottom": res.plans[0].zone.bottom, "top": res.plans[0].zone.top,
                                "reason": "daily limit reached"})

    for s, pos in positions.items():       # anything still open at the end of data
        if pos is not None and pos.state == "open":
            last = feats[s].iloc[-1]
            pos._exit_all(feats[s].index[-1], last["close"], "end of data")
            trades.append(pos.record())
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=TRADE_COLUMNS)
    skipped_df = pd.DataFrame(skipped) if skipped else pd.DataFrame(columns=SKIP_COLUMNS)
    return trades_df, skipped_df
