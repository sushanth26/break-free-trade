"""Live runtime: one async process, 4:00-20:00 ET, alerts only.

Each 5m bar close: new bars → features → zones → regime → news (Claude judge)
→ SymbolEngine (the same code as the backtest) → paper position tracking with
the same Position/FillModel → Telegram alerts. Re-plan events call Claude; on
timeout or invalid output the rule-based alert goes out without the AI note.
Every event, alert, AI call and trade is logged to SQLite.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

import config
from alerts import formatter as fmt
from backtest.fills import FillModel
from backtest.trade_backtest import RiskManager
from data.base import normalize_bars
from engine.features import compute_features
from engine.pipeline import BarContext, SymbolEngine
from engine.profile import round_step
from engine.regime import market_regime, regime_at
from engine.settings import EngineSettings
from engine.trade import Position
from engine.zones import label_zones
from live.scheduler import jobs_due, next_bar_close
from live.zones_live import LiveZoneSource

RULE_BIAS = {"bullish": "long", "gap_filled": "long", "bearish": "short", "gap_filling": "wait", "choppy": "wait"}


@dataclass
class SymbolState:
    symbol: str
    bars: pd.DataFrame
    daily: pd.DataFrame
    zones: Callable
    engine: SymbolEngine
    position: Position | None = None
    news_bias: str = ""
    news_bias_until: pd.Timestamp | None = None
    last_headline: pd.Timestamp | None = None
    recent_events: list = field(default_factory=list)


class LiveRunner:
    def __init__(self, symbols: list[str], history: dict[str, tuple[pd.DataFrame, pd.DataFrame]],
                 settings: EngineSettings, telegram, store=None, ai=None,
                 news_source: Callable[[list[str], pd.Timestamp], pd.DataFrame] | None = None,
                 economic: pd.DataFrame | None = None, zone_source_factory: Callable | None = None,
                 market_fn: Callable | None = None, fills: FillModel = FillModel()):
        self.settings = settings
        self.telegram = telegram
        self.store = store
        self.ai = ai
        self.news_source = news_source
        self.economic = economic
        self.market_fn = market_fn
        self.fills = fills
        self.risk = RiskManager()
        self.prev_regime: str | None = None
        self.done_jobs: set[str] = set()
        self.last_data = pd.Timestamp.now(tz=config.TZ)
        self.heartbeat_sent = False
        factory = zone_source_factory or (lambda s: LiveZoneSource(s, settings))
        self.state: dict[str, SymbolState] = {}
        for s in symbols:
            bars, daily = history[s]
            zs = factory(s)
            st = SymbolState(s, normalize_bars(bars), daily, zs, SymbolEngine(s, zs, settings))
            self.state[s] = st
        self.context = {s: self.state[s] for s in config.REGIME_SYMBOLS if s in self.state}

    # ------------------------------------------------------------------ output
    def _alert(self, symbol: str, kind: str, text: str | None, t=None):
        if not text:
            return
        ok = self.telegram.send(text)
        if self.store:
            self.store.alert(symbol, kind, text, ok, t)

    # ------------------------------------------------------------------ helpers
    def _window(self, st: SymbolState) -> pd.DataFrame:
        days = st.bars.index.normalize().unique()[-config.LIVE_HISTORY_SESSIONS:]
        return st.bars[st.bars.index.normalize() >= days[0]] if len(days) else st.bars

    def _market(self, now) -> tuple[str, str, bool]:
        if self.market_fn:
            return self.market_fn(now)
        if not self.context:
            return "choppy", "", False
        feats = {s: compute_features(self._window(st), st.daily) for s, st in self.context.items()}
        return regime_at(market_regime(feats), now)

    def _zones_info(self, st: SymbolState, now, price: float) -> list[dict]:
        return [{"label": lbl, "bottom": round(z.bottom, 2), "top": round(z.top, 2),
                 "timeframes": "+".join(z.timeframes)} for lbl, z in label_zones(st.zones(now), price)]

    def _news(self, st: SymbolState, now, price: float, regime: str):
        """New headlines for this symbol → judged bias (expires after the catalyst lookback)."""
        if self.news_source is None:
            return None, False
        since = st.last_headline or now - pd.Timedelta(minutes=config.CATALYST_LOOKBACK_MIN)
        news = self.news_source([st.symbol], since)
        news = news[news["published_at"] < now] if len(news) else news
        if len(news):
            st.last_headline = news["published_at"].max() + pd.Timedelta("1s")
            if self.ai is not None:
                from ai.news_judge import bias_from, judge_headline
                for _, h in news.iterrows():
                    j = judge_headline(self.ai, h["headline"], h["published_at"], st.symbol, price,
                                       self._zones_info(st, now, price), regime)
                    b = bias_from(j)
                    if b:
                        st.news_bias = b
                        st.news_bias_until = now + pd.Timedelta(minutes=config.CATALYST_LOOKBACK_MIN)
        if st.news_bias_until is not None and now > st.news_bias_until:
            st.news_bias, st.news_bias_until = "", None
        catalyst = st.last_headline is not None and \
            now - st.last_headline <= pd.Timedelta(minutes=config.CATALYST_LOOKBACK_MIN)
        return (news if len(news) else None), catalyst

    # ------------------------------------------------------------------ per bar
    def on_bars(self, now: pd.Timestamp, new: dict[str, pd.DataFrame]):
        """Process newly closed bars (``now`` = the bar close)."""
        if not new:
            return
        self.last_data, self.heartbeat_sent = now, False
        for s, b in new.items():
            st = self.state[s]
            st.bars = normalize_bars(pd.concat([st.bars, b]))
        regime, gap_dir, confirmed = self._market(now)
        prev_regime, self.prev_regime = self.prev_regime, regime
        in_window = False
        if self.economic is not None and len(self.economic):
            before, after = (pd.Timedelta(minutes=m) for m in config.NEWS_WINDOW)
            in_window = bool(((self.economic["time"] + before <= now) & (now <= self.economic["time"] + after)).any())

        for s in new:
            st = self.state[s]
            win = self._window(st)
            feats = compute_features(win, st.daily)
            t = feats.index[-1]
            row = feats.iloc[-1]
            if hasattr(st.zones, "update"):
                st.zones.update(st.bars, st.daily)
            headlines, catalyst = self._news(st, now, float(row["close"]), regime)
            ctx = BarContext(regime=regime, gap_dir=gap_dir, regime_confirmed=confirmed,
                             prev_regime=prev_regime, catalyst=catalyst, news_bias=st.news_bias,
                             in_news_window=in_window, headlines=headlines)
            if st.engine.prev_row is None and len(feats) > 1:
                st.engine.prev_row = feats.iloc[-2]

            # 1) open alert/position first (intrabar), as in the backtest
            if st.position is not None:
                bar = {k: row[k] for k in ("open", "high", "low", "close", "volume")}
                for a in st.position.on_bar(t, bar, row, news_against=ctx.news_against(st.position.plan.direction)):
                    if a.kind != "filled":
                        self._alert(s, a.kind, fmt.action(s, a), now)
                if st.position.state in ("closed", "cancelled"):
                    rec = st.position.record()
                    if self.store:
                        self.store.trade(s, rec)
                    if st.position.state == "closed":
                        self.risk.record(now, st.position.pnl - st.position.commission)
                    st.position = None

            # 2) engine at the bar close
            res = st.engine.on_bar(t, row, win, ctx, feats["rvol"])
            st.recent_events = (st.recent_events + [{"kind": e.kind, **e.detail} for e in res.events])[-10:]
            for ev in res.events:
                if self.store:
                    self.store.event(ev)
            labels = {id(z): lbl for lbl, z in label_zones(st.zones(now), float(row["close"]))}
            for z, score in res.watch:
                self._alert(s, "watch", fmt.watch(s, labels.get(id(z), "zone"), z, score), now)
            if self.settings.entry_mode == "confirmed":
                for u in res.updates:
                    if u.changed and u.stage == "rejection":
                        self._alert(s, "possible_bounce", fmt.possible_bounce(s, labels.get(id(u.zone), "zone")), now)
            if st.position is None and res.plans:
                plan = res.plans[0]
                if self.risk.allows(now):
                    st.position = Position(plan, self.fills)
                    self._alert(s, "entry", fmt.entry(plan, plan.shares * plan.risk_per_share), now)
                else:
                    self._alert(s, "info", fmt.info(f"{s} setup skipped: daily limit reached"), now)
            for ev in res.events:
                if ev.replan and (s in config.REGIME_SYMBOLS or st.position is not None):
                    self._replan(st, ev, row, regime, now)

    def _replan(self, st: SymbolState, ev, row, regime: str, now):
        bias = RULE_BIAS.get(regime, "wait")
        what = ev.kind.replace("_", " ")
        consequence = {"long": "longs only", "short": "shorts only", "wait": "no new entries"}[bias]
        note = ""
        if self.ai is not None:
            from ai.replanner import replan
            pos = None
            if st.position is not None:
                p = st.position.plan
                pos = {"direction": p.direction, "entry": p.entry, "stop": st.position.stop, "t1": p.t1, "t2": p.t2,
                       "state": st.position.state}
            r = replan(self.ai, st.symbol, {"atr_5m": float(row["atr"]), "round_step": round_step(row["close"]),
                                             "price": float(row["close"])},
                       self._zones_info(st, now, float(row["close"])), regime, pos,
                       {"kind": ev.kind, **ev.detail}, st.recent_events)
            if r is not None and r.action == "replan":
                bias, note = r.bias, r.reason
                consequence = {"long": "longs only", "short": "shorts only", "wait": "no new entries"}[bias]
        self._alert(st.symbol, "replan", fmt.replan(st.symbol, what, bias, consequence, note), now)

    # ------------------------------------------------------------------ scheduled jobs
    def run_jobs(self, now: pd.Timestamp, archive: Callable | None = None, premarket: Callable | None = None):
        for job in jobs_due(now, self.done_jobs):
            self.done_jobs.add(job)
            if job == "premarket_plan" and premarket:
                self._alert("ALL", "premarket", premarket(self, now), now)
            elif job == "cutoff_reminder":
                open_pos = [f"{s} {st.position.plan.direction} {st.position.shares_open} sh stop {st.position.stop:.2f}"
                            for s, st in self.state.items() if st.position and st.position.state == "open"]
                self._alert("ALL", "reminder", fmt.info("No new entries after 15:45. Open: " +
                                                        ("; ".join(open_pos) or "none")), now)
            elif job == "archive" and archive:
                archive(self, now)

    def check_heartbeat(self, now: pd.Timestamp):
        expected = next_bar_close(self.last_data) + pd.Timedelta(seconds=config.POLL_DELAY_S)
        if now - expected > pd.Timedelta(seconds=config.HEARTBEAT_TIMEOUT_S) and not self.heartbeat_sent:
            self.heartbeat_sent = True
            self._alert("ALL", "heartbeat", fmt.info(f"No market data since {self.last_data:%H:%M}. Check the feed."), now)

    async def run(self, source, archive=None, premarket=None, clock: Callable = None):
        """Main loop until the shutdown job. ``source.poll(now)`` returns new closed bars."""
        clock = clock or (lambda: pd.Timestamp.now(tz=config.TZ))
        while "shutdown" not in self.done_jobs:
            now = clock()
            wake = next_bar_close(now) + pd.Timedelta(seconds=config.POLL_DELAY_S)
            await asyncio.sleep(max((wake - now).total_seconds(), 0))
            now = clock()
            bar_close = now.floor("5min")
            try:
                new = await asyncio.to_thread(source.poll, bar_close)
                self.on_bars(bar_close, new)
            except Exception as e:  # keep running; reconnect happens on the next poll
                self._alert("ALL", "error", fmt.info(f"data error: {type(e).__name__}: {e}"), now)
            self.check_heartbeat(clock())
            self.run_jobs(clock(), archive, premarket)


def rule_premarket(runner: LiveRunner, now) -> str:
    """Fallback premarket message: labelled zones per ticker (used when Claude is off or fails)."""
    lines = ["Premarket levels"]
    for s, st in runner.state.items():
        if not len(st.bars):
            continue
        price = float(st.bars["close"].iloc[-1])
        zs = label_zones(st.zones(now), price)[:4]
        lines.append(f"{s} {price:.2f} · " + " · ".join(f"{l} {z.bottom:.2f}–{z.top:.2f}" for l, z in zs))
    return "\n".join(lines)
