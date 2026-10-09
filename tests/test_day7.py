import json
from types import SimpleNamespace

import pandas as pd
import pytest

import config
from ai.client import AIClient, call_cost, load_prompt
from ai.news_judge import bias_from
from ai.replanner import allowed_levels
from ai.schemas import NewsJudgment, PremarketPlan, Replan, Scenario
from alerts import formatter as fmt
from alerts.telegram import Telegram
from backtest.labels import ZoneTimeline
from backtest.trade_backtest import run_backtest
from data.stream import BarBuilder, PollingSource
from engine.trade import Action
from live.runner import LiveRunner
from live.scheduler import jobs_due, next_bar_close
from live.store import Store
from live.zones_live import LiveZoneSource
from engine.settings import EngineSettings
from config import ZoneConfig
from tests.synthetic import daily_from, random_bars
from tests.test_trading import Zn, _scripted_input

ET = "America/New_York"


# ------------------------------------------------------------------ AI client with a fake SDK
class FakeMessages:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []

    def parse(self, **kw):
        self.calls.append(kw)
        b = self.behaviour
        if isinstance(b, Exception):
            raise b
        return b


def fake_ai(behaviour, log):
    client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(behaviour)))
    return AIClient(client=client, log=log), client.beta.messages


def resp(parsed, stop="end_turn"):
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop, model="claude-sonnet-5-5",
                           usage=SimpleNamespace(input_tokens=1000, output_tokens=100,
                                                 cache_creation_input_tokens=0, cache_read_input_tokens=0))


def test_ai_ok_logs_and_request_shape():
    logs = []
    j = NewsJudgment(relevance="ticker", direction="bearish", impact="high", action="exit", reason="guidance cut")
    ai, msgs = fake_ai(resp(j), logs.append)
    out = ai.ask("news_judge", load_prompt("news_judge"), {"headline": "x"}, NewsJudgment)
    assert out == j and bias_from(out) == "bearish"
    kw = msgs.calls[0]
    assert kw["model"] == config.CLAUDE_MODEL and kw["timeout"] == config.CLAUDE_TIMEOUT_S
    assert kw["output_format"] is NewsJudgment and kw["fallbacks"] == "default"
    assert logs[0]["status"] == "ok" and logs[0]["cost_usd"] == pytest.approx(call_cost(resp(j).usage))
    assert json.loads(logs[0]["input"]) == {"headline": "x"}


def test_ai_guardrails():
    logs = []
    bad_price = Replan(action="replan", bias="long", entry_zone="S1", entry=571.37, stop=569.0, reason="r")
    ai, _ = fake_ai(resp(bad_price), logs.append)
    assert ai.ask("replanner", "p", {}, Replan, allowed_prices=[570.0, 569.0]) is None
    assert "invented prices" in logs[-1]["status"]

    no_reason = NewsJudgment(relevance="ticker", direction="bullish", impact="high", action="flip_bias", reason=" ")
    ai, _ = fake_ai(resp(no_reason), logs.append)
    assert ai.ask("news_judge", "p", {}, NewsJudgment) is None

    ai, _ = fake_ai(resp(None, stop="refusal"), logs.append)
    assert ai.ask("news_judge", "p", {}, NewsJudgment) is None and logs[-1]["status"] == "refusal"

    import anthropic
    import httpx2
    ai, _ = fake_ai(anthropic.APITimeoutError(request=httpx2.Request("POST", "https://x")), logs.append)
    assert ai.ask("news_judge", "p", {}, NewsJudgment) is None and logs[-1]["status"] == "timeout"


def test_allowed_levels_and_premarket_schema():
    lv = allowed_levels([{"bottom": 570.0, "top": 571.0}], atr=2.0, extra=[575.0])
    assert {570.0, 571.0, 569.8, 571.2, 575.0} <= set(lv)
    PremarketPlan(scenarios=[Scenario(ticker="DELL", regime="bullish", plan="If holds S1, long", levels=[570.0])])


# ------------------------------------------------------------------ alerts, scheduler, store, stream
def test_alert_formats_match_plan():
    z = Zn(570.0, 571.0)
    assert fmt.watch("DELL", "S1", z, 85) == "🟡 Watch · DELL at S1 570.00–571.00 (85) · watching"
    assert fmt.action("DELL", Action(None, "target1", 582.57, 10, "", 572.10)) == \
        "🟢 Target · DELL T1 hit · sell 1/3 · stop → 572.10"
    assert fmt.replan("SPY", "vwap lost", "wait", "no new entries").startswith("🔵 Re-plan · SPY vwap lost")
    assert fmt.action("DELL", Action(None, "filled")) is None


def test_scheduler_and_telegram_dry_run(tmp_path):
    t = pd.Timestamp("2026-10-19 08:31", tz=ET)
    assert jobs_due(t, set()) == ["connect", "premarket_plan"]
    assert jobs_due(t, {"connect"}) == ["premarket_plan"]
    assert next_bar_close(pd.Timestamp("2026-10-19 09:33:10", tz=ET)) == pd.Timestamp("2026-10-19 09:35", tz=ET)
    tg = Telegram(token="", chat_id="", dry_run=True)
    assert tg.send("hi") and tg.sent == ["hi"]
    s = Store(tmp_path / "a.sqlite")
    s.alert("X", "watch", "hi", True)
    assert len(s.rows("alerts")) == 1


def test_bar_builder_and_polling():
    bb = BarBuilder()
    t0 = pd.Timestamp("2026-10-19 09:30:01", tz=ET)
    assert bb.on_tick(t0, 10.0, 100) == []
    bb.on_tick(t0 + pd.Timedelta("2min"), 10.5, 50)
    bb.on_tick(t0 + pd.Timedelta("3min"), 9.8, 50)
    out = bb.on_tick(t0 + pd.Timedelta("5min"), 10.1, 10)
    assert len(out) == 1 and out[0].name == pd.Timestamp("2026-10-19 09:30", tz=ET)
    assert (out[0]["open"], out[0]["high"], out[0]["low"], out[0]["close"], out[0]["volume"]) == (10.0, 10.5, 9.8, 9.8, 200)

    bars = random_bars(days=1)
    prov = SimpleNamespace(get_bars=lambda sym, tf, count=6: bars.iloc[:12])
    src = PollingSource(prov, ["A"])
    now = bars.index[11] + pd.Timedelta("5min")
    assert len(src.poll(now)["A"]) == 12
    assert src.poll(now) == {}


# ------------------------------------------------------------------ live = backtest
def test_live_zone_source_matches_backtest_timeline():
    from backtest.zone_backtest import SymbolData, build_timeline
    bars = random_bars(days=30, seed=8)
    st = EngineSettings(zone=ZoneConfig(pivot_period=5, channel_width_pct=2.0), timeframes=("5m", "30m"))
    full = build_timeline(SymbolData("X", bars, daily_from(bars)), st.timeframes, st.zone)
    live = LiveZoneSource("X", st)
    for k in (1500, 2000, len(bars) - 1):
        now = bars.index[k] + pd.Timedelta("5min")
        live.update(bars.iloc[: k + 1])
        a = [(z.bottom, z.top, z.timeframes) for z in full(now)]
        b = [(z.bottom, z.top, z.timeframes) for z in live(now)]
        assert a == b


def test_live_runner_alerts_match_backtest_trade(tmp_path):
    inp, st = _scripted_input()
    trades, _ = run_backtest(inp, st)
    d = inp.datas["AAA"]
    bars = d.bars
    last_day = bars.index.normalize()[-1]
    hist = bars[bars.index.normalize() < last_day]
    zones = inp.timelines[("AAA", st.timeframes, st.zone)]
    tg = Telegram(dry_run=True)
    runner = LiveRunner(["AAA"], {"AAA": (hist, d.daily)}, st, tg, Store(tmp_path / "l.sqlite"),
                        zone_source_factory=lambda s: zones, market_fn=lambda now: ("choppy", "", True))
    for t in bars.index[bars.index.normalize() == last_day]:
        runner.on_bars(t + pd.Timedelta("5min"), {"AAA": bars.loc[[t]]})
    entry = [m for m in tg.sent if m.startswith("🟢 Entry")]
    tr = trades.iloc[0]
    assert len(entry) == 1
    assert f"entry {tr['entry']:.2f}" in entry[0] and f"stop {tr['stop']:.2f}" in entry[0]
    assert f"T1 {tr['t1']:.2f}" in entry[0]
    assert any(m.startswith("🟢 Target · AAA T1 hit") for m in tg.sent)
    assert any("end of day" in m for m in tg.sent)
    assert len(runner.store.rows("trades")) == 1
