import pandas as pd
import pytest

from backtest.fills import FillModel
from backtest.metrics import max_drawdown_r, passes, summarize, win_rate_interval
from backtest.trade_backtest import BacktestInput, RiskManager, run_backtest
from backtest.zone_backtest import SymbolData
from config import ZoneConfig
from engine.features import compute_features
from engine.regime import market_regime
from engine.settings import EngineSettings
from engine.trade import Position, plan_trade
from engine.zones import Zone
from tests.synthetic import daily_from, random_bars

ET = "America/New_York"
T0 = pd.Timestamp("2026-03-02 10:00", tz=ET)


def Zn(b, t):
    return Zone(top=t, bottom=b, timeframes=("5m",), pivots=(), strength_raw=40, created_at=T0)


def bar(o, h, l, c, v=1000.0):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


NOSLIP = FillModel(slippage_pct=0.0, commission_per_share=0.0)


def test_target_needs_trade_through():
    f = NOSLIP
    assert f.target_fill("long", 582.00, bar(580, 581.91, 579, 581)) is None
    assert f.target_fill("long", 582.00, bar(580, 582.00, 579, 581)) is None
    assert f.target_fill("long", 582.00, bar(580, 582.01, 579, 581)) == 582.00


def test_entry_touch_vs_adverse_selection():
    b = bar(100.5, 100.6, 100.0, 100.4)
    assert NOSLIP.entry_fill("long", 100.0, b) == (100.0, True)
    assert FillModel(slippage_pct=0, adverse_selection=True).entry_fill("long", 100.0, b) is None
    assert FillModel(slippage_pct=0, adverse_selection=True).entry_fill("long", 100.0, bar(100.5, 100.6, 99.98, 100.4)) == (100.0, False)


def test_slippage_and_gap_through_stop():
    f = FillModel(slippage_pct=0.02, commission_per_share=0.005)
    assert f.stop_fill("long", 99.0, bar(98.0, 98.5, 97.5, 98.2)) == pytest.approx(98.0 * (1 - 0.0002))
    assert f.commission(100) == pytest.approx(0.5)


def test_plan_trade_levels():
    z = Zn(99.5, 100.0)
    zones = [z, Zn(103.0, 103.5), Zn(106.0, 106.5)]
    plan, why = plan_trade("X", "long", 100.3, 99.6, 100.3, z, zones, atr=0.5, round_step=1.0, signal_time=T0)
    assert why == "" and plan.stop == pytest.approx(99.55)
    assert plan.t1 == pytest.approx(102.95)              # next zone bottom − 0.1 ATR
    assert plan.t2 == pytest.approx(103.95)              # round 104 − 0.1 ATR (nearer than zone 106)
    assert plan.shares == int(100 / 0.75)
    far = [z, Zn(110, 111)]
    assert plan_trade("X", "long", 100.3, 99.6, 100.3, z, far, 0.5, 1.0, T0)[0] is None   # > 5R away


def test_position_t1_then_breakeven_stop():
    z = Zn(99.5, 100.0)
    plan, _ = plan_trade("X", "long", 100.3, 99.6, 100.3, z, [z, Zn(103.0, 103.5)], 0.5, 1.0, T0)
    pos = Position(plan, NOSLIP)
    pos.on_bar(T0, bar(100.6, 100.7, 100.25, 100.5))             # fills at 100.3
    assert pos.state == "open" and pos.entry_fill == 100.3
    pos.on_bar(T0, bar(100.5, 103.0, 100.4, 102.9))              # T1 102.95 traded through
    assert pos.t1_hit and pos.win and pos.stop == 100.3
    pos.on_bar(T0, bar(102.0, 102.1, 100.2, 100.4))              # back to breakeven
    assert pos.state == "closed" and pos.win
    assert pos.r_multiple > 0


def test_position_false_bounce_exit_is_loss():
    z = Zn(99.5, 100.0)
    plan, _ = plan_trade("X", "long", 100.3, 99.6, 100.3, z, [z, Zn(103.0, 103.5)], 0.5, 1.0, T0)
    pos = Position(plan, NOSLIP)
    pos.on_bar(T0, bar(100.6, 100.7, 100.25, 100.5))
    pos.on_bar(T0, bar(100.4, 100.45, 99.7, 99.8))               # close back in zone
    assert pos.state == "closed" and pos.win is False and "false bounce" in pos.exit_reason


def test_pending_cancels():
    z = Zn(99.5, 100.0)
    plan, _ = plan_trade("X", "long", 100.3, 99.6, 100.3, z, [z, Zn(103.0, 103.5)], 0.5, 1.0, T0)
    pos = Position(plan, NOSLIP)
    pos.on_bar(T0, bar(100.6, 100.9, 100.4, 100.8))
    pos.on_bar(T0, bar(100.8, 101.0, 100.5, 100.9))
    assert pos.state == "cancelled"


def test_metrics_and_risk_manager():
    assert win_rate_interval(120, 200)[0] == pytest.approx(0.6 - 1.96 * (0.6 * 0.4 / 200) ** 0.5)
    assert max_drawdown_r(pd.Series([1, -1, -1, 2, -3])) == 3
    t = pd.DataFrame({"state": "closed", "win": [True, True, False], "r": [1.5, 0.8, -1.0],
                      "fill_time": pd.to_datetime(["2026-03-02 10:00"] * 3).tz_localize(ET)})
    s = summarize(t)
    assert s["win_rate"] == pytest.approx(2 / 3) and s["profit_factor"] == pytest.approx(2.3)
    assert passes(s)["trades"] is False
    rm = RiskManager()
    rm.record(T0, -50)
    rm.record(T0, -50)
    assert not rm.allows(T0) and rm.allows(T0 + pd.Timedelta(days=1))


def _scripted_input():
    from backtest.labels import ZoneTimeline
    from tests.synthetic import scripted_bounce_bars
    b = scripted_bounce_bars()
    d = SymbolData("AAA", b, daily_from(b))
    t0 = b.index[0]
    zones = [Zn(99.5, 100.0), Zn(102.0, 102.3)]
    market = pd.DataFrame({"regime": "choppy", "gap_dir": "", "confirmed": True},
                          index=d.feats.index + pd.Timedelta("5min"))
    st = EngineSettings(min_zone_score=0, require_regime_agree=False, entry_mode="early", allow_short=False)
    inp = BacktestInput({"AAA": d}, market)
    inp.timelines[("AAA", st.timeframes, st.zone)] = ZoneTimeline([t0], [zones])
    return inp, st


def test_backtest_scripted_bounce_wins():
    inp, st = _scripted_input()
    trades, skipped = run_backtest(inp, st)
    closed = trades[trades["state"] == "closed"]
    assert len(closed) == 1, (trades.to_dict("records"), skipped.to_dict("records"))
    tr = closed.iloc[0]
    assert tr["direction"] == "long" and tr["entry"] == 100.08 and tr["win"]
    assert tr["stop"] < 99.6 and 101.5 < tr["t1"] < 102.0
    assert tr["r"] > 0
    # adverse selection: the fill bar traded through 100.08 (low 100.0), so it still fills
    adv, _ = run_backtest(inp, st, fills=FillModel(adverse_selection=True))
    assert (adv["state"] == "closed").sum() == 1


def test_backtest_runs_on_random_data():
    inp = _input()
    st = EngineSettings(zone=ZoneConfig(pivot_period=5, channel_width_pct=3.0), min_zone_score=0,
                        require_regime_agree=False, entry_mode="early")
    trades, skipped = run_backtest(inp, st, symbols=["AAA"])
    assert isinstance(trades, pd.DataFrame) and isinstance(skipped, pd.DataFrame)


def _input(days=25):
    datas = {}
    for i, s in enumerate(("SPY", "QQQ", "AAA")):
        b = random_bars(days=days, start_price=100 + 20 * i, seed=30 + i, extended=True)
        datas[s] = SymbolData(s, b, daily_from(b))
    market = market_regime({s: datas[s].feats for s in ("SPY", "QQQ")})
    return BacktestInput(datas, market)
